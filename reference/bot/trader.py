import os
import json
import time
from typing import Dict, Optional

from bot.config.config_loader import ConfigLoader
from bot.data.data_provider import MarketDataProvider
from bot.api.exchange import QUOTE, Broker, CcxtBroker, PaperBroker
from bot.record.recorder import log_order, log_trade_close, log_liquidation
from bot.record.logger import setup_file_logger
from bot.data.signal.indicators import compute_indicators
from bot.data.signal.execution_filter import basic_execution_ok, momentum_execution_ok, iceberg_execution_ok
from bot.trading_logic.signal.MACD.isBullish import check as macd_bullish
from bot.trading_logic.signal.MACD.divergence import bearish as macd_bearish_divergence
from bot.strategy import SIGNAL_KEYS, entry_signal_ok, signal_statuses
from bot.data.types import Position
from bot.core.parallel import parallel_dict
from bot.core.persistence import load_json, save_json
from bot.flow_control.global_stop_loss import update_daily_peak
from bot.flow_control.daily_rollover import write_daily_pnl as fc_write_daily_pnl
from bot.flow_control.on_end_liquidate import should_liquidate_by_age
from bot.flow_control.on_end_liquidate import persist_rotation as fc_persist_rotation
from bot.flow_control.rate_limiter import RateLimiter
from bot.flow_control.stop_loss_take_profit import evaluate_dynamic_sl_tp

def _load_dotenv() -> None:
    """Load a local .env (never committed) for the live entry point only, so tests stay hermetic."""
    try:
        from dotenv import load_dotenv, find_dotenv
        load_dotenv(find_dotenv(usecwd=True), override=False)
        base_dir = os.path.dirname(__file__)
        load_dotenv(os.path.join(base_dir, ".env"), override=False)
        load_dotenv(os.path.join(base_dir, "config", ".env"), override=False)
    except Exception:
        pass


class Trader:
    def __init__(self, config_path: str, broker: Optional[Broker] = None, market_data=None) -> None:
        """Orders and balances go through `broker` (default: a PaperBroker on this config's fees and
        initial_capital_in_usd); tests inject fakes so construction makes no network call."""
        setup_file_logger()
        self.cfg_loader = ConfigLoader(config_path)
        # Honor data.source preference (ccxt | horus)
        preferred_source = str(self.cfg_loader.get().raw.get("data", {}).get("source", "ccxt"))
        self.market_data = market_data if market_data is not None else MarketDataProvider(preferred_source=preferred_source)
        if broker is None:
            raw = self.cfg_loader.get().raw
            broker = PaperBroker(self.market_data.fetch_ticker_price,
                                 fee_rate=float(raw.get("transaction_fee", 0.0)),
                                 slippage_bps=float((raw.get("portfolio") or {}).get("slippage_bps", 1.0)),
                                 cash=float(raw.get("initial_capital_in_usd", 50000)))
        self.broker: Broker = broker
        self.positions: Dict[str, Position] = {}
        rate = int(self.cfg_loader.get().rate_limit.get("orders_per_min", 15))
        self.rate_limiter = RateLimiter(rate)
        # Initialize last_good_equity before first fetch to avoid attribute errors
        self._last_good_equity: float = 0.0
        self.peak_equity = self._fetch_equity()  # display peak (mark-to-market)
        self._last_good_equity = self.peak_equity if self.peak_equity and self.peak_equity > 0 else 0.0
        self._today = time.strftime("%Y-%m-%d")
        # Separate guard peak (USD free + pack) for 10% max drawdown logic
        self._guard_peak: float = 0.0
        self._guard_peak_date: str = self._today
        # Last known good USD free (for guard equity)
        self._last_usd_free: float = 0.0
        # Daily peak reset state (based on configured daily_check_time)
        self._last_peak_reset_date: str = self._today
        # Persist/display peaks across restarts
        self._peaks_path = os.path.join("record", "peaks.json")
        try:
            peaks = load_json(self._peaks_path) or {}
            if isinstance(peaks, dict) and peaks.get("date") == self._today:
                self.peak_equity = float(peaks.get("display_peak", self.peak_equity) or self.peak_equity)
                self._guard_peak = float(peaks.get("guard_peak", self._guard_peak) or self._guard_peak)
        except Exception:
            pass
        # Per-symbol fetch cadence control (in seconds) and simple OHLCV cache
        self._last_fetch_ts: Dict[str, float] = {}
        self._ohlcv_cache: Dict[str, tuple] = {}
        self._mtd_path = os.path.join("record", "mtd_stats.json")
        self._mtd = load_json(self._mtd_path)
        self._slow_flag_path = os.path.join("record", "slow_stop.flag")
        self._alloc_path = os.path.join("record", "allocation_overrides.json")
        self._alloc = load_json(self._alloc_path)
        self._cooldown_path = os.path.join("record", "cooldown.json")
        self._cooldown = load_json(self._cooldown_path)
        # Throttle console summary spam
        self._last_console_summary_ts: float = 0.0
        # Debounce global drawdown guard to avoid transient triggers
        self._dd_breach_count: int = 0
        # Snapshot of config for change detection notice
        try:
            self._cfg_snapshot: str = json.dumps(self.cfg_loader.get().raw, sort_keys=True)
        except Exception:
            self._cfg_snapshot = ""
        # Dashboard status output path
        self._dash_status_path = os.path.join("record", "dashboard_status.json")
        # Daily per-coin realized loss tracker
        self._daily_loss_path = os.path.join("record", "daily_losses.json")
        self._daily_losses = load_json(self._daily_loss_path) or {}
        # Persist per-coin peak equity for pack allocation updates
        self._coin_peak_path = os.path.join("record", "coin_peak_equity.json")
        self._coin_peaks = load_json(self._coin_peak_path) or {}
        # Persist last daily reset date to survive restarts
        self._last_reset_path = os.path.join("record", "last_daily_reset.json")
        try:
            last_reset = load_json(self._last_reset_path) or {}
            self._last_peak_reset_date = str(last_reset.get("date", "")) or ""
        except Exception:
            pass
        # Establish initial equity baseline from API once and persist
        self._initial_equity_path = os.path.join("record", "initial_equity.json")
        self.initial_equity = self._load_initial_equity()
        if not self.initial_equity or self.initial_equity <= 0:
            try:
                ieq = float(self._fetch_equity() or 0.0)
                if ieq > 0:
                    self.initial_equity = ieq
                    save_json(self._initial_equity_path, {"initial_equity": ieq, "ts": time.time()})
            except Exception:
                self.initial_equity = float(self._last_good_equity or 0.0)
        
        # Single-coin mode: set allocation based on percentage of initial equity
        cfg = self.cfg_loader.get()
        # Initialize slow-stop status tracking for change detection
        self._last_slow_stop_status = self._slow_stop_enabled(cfg)
        # Log slow-stop status on initialization
        if self._last_slow_stop_status:
            if cfg.detail_console_output:
                self._log("[SLOW-STOP] Mode ENABLED: No new entries, but stop-loss and take-profit will continue")
        single_coin_mode = bool(cfg.portfolio.get("single_coin_mode", False))
        if single_coin_mode and self.initial_equity and self.initial_equity > 0:
            single_coin_symbol = str(cfg.portfolio.get("single_coin_symbol", "BTC/USDT"))
            pack_percentage = float(cfg.portfolio.get("single_coin_pack_percentage", 0.5))
            pack_percentage = max(0.0, min(1.0, pack_percentage))  # clamp to [0, 1]
            pack_usd = self.initial_equity * pack_percentage
            self._alloc[single_coin_symbol] = pack_usd
            save_json(self._alloc_path, self._alloc)
            if cfg.detail_console_output:
                self._log(f"[SINGLE-COIN] Mode enabled: {single_coin_symbol} | Allocation: {pack_usd:.2f} USD ({pack_percentage*100:.1f}% of initial equity {self.initial_equity:.2f})")

    def _signal_statuses(self, indicators: Dict, flags: Dict, orderbook: Optional[Dict] = None, current_price: float = 0.0, ob_config: Optional[Dict] = None) -> Dict[str, bool]:
        """Per-signal statuses from the pluggable strategy (bot/strategy.py), shared with the backtester."""
        return signal_statuses(indicators, flags, orderbook, current_price, ob_config)

    def _fetch_equity(self) -> float:
        """Account value in USDT: quote cash plus every other asset at its USDT price.

        Tries the broker balance twice; if both reads fail or value nothing, returns last-good equity.
        """
        for _ in range(2):
            try:
                total = self.broker.fetch_balance().get("total", {})
                equity = float(total.get(QUOTE, 0.0) or 0.0)
                for asset, qty in total.items():
                    if asset == QUOTE or float(qty or 0.0) <= 0:
                        continue
                    price = float(self.market_data.fetch_ticker_price(f"{asset}/{QUOTE}") or 0.0)
                    if price > 0:
                        equity += float(qty) * price
                if equity > 0:
                    return equity
            except Exception:
                pass
        # Last resort: last good value (may be 0 if none yet)
        return float(self._last_good_equity or 0.0)

    def _load_initial_equity(self) -> float:
        try:
            data = load_json(self._initial_equity_path)
            v = float((data or {}).get("initial_equity", 0.0))
            return v if v > 0 else 0.0
        except Exception:
            return 0.0

    def _compute_pack_total(self, enabled_symbols: list[str]) -> float:
        cfg = self.cfg_loader.get()
        base_usd = float(cfg.portfolio.get("usd_per_trade", 10000.0))
        total = 0.0
        for sym in enabled_symbols:
            total += float(self._alloc.get(sym, base_usd))
        return total

    def _guard_equity(self, enabled_symbols: list[str]) -> tuple[float, bool]:
        """Return (guard_equity, is_valid_now).

        guard_equity = usd_free_valid_or_last + pack allocations.
        is_valid_now indicates whether we used a fresh (nonzero) USD free from API this cycle.
        """
        usd_free_now = self._available_usdt()
        # If current reading invalid, fallback to last good
        is_valid_now = bool(usd_free_now and usd_free_now > 0)
        if is_valid_now:
            self._last_usd_free = usd_free_now
        usd_free_effective = usd_free_now if is_valid_now else float(self._last_usd_free or 0.0)
        pack_total = self._compute_pack_total(enabled_symbols)
        return float(usd_free_effective + pack_total), is_valid_now

    def _usdt_for_trade(self, symbol: str) -> float:
        # Use config first, then env, then defaults (all USD/USDT units)
        cfg = self.cfg_loader.get()
        # Detect and report config changes (lightweight)
        try:
            _new_snapshot = json.dumps(cfg.raw, sort_keys=True)
            if _new_snapshot != self._cfg_snapshot:
                # Compute a shallow diff of toggles we care about
                changed_keys = []
                try:
                    old = json.loads(self._cfg_snapshot) if self._cfg_snapshot else {}
                    new = json.loads(_new_snapshot)
                    for k in ["signal_portfolio", "portfolio", "stop_loss_take_gain", "crypto_list", "data"]:
                        if old.get(k) != new.get(k):
                            changed_keys.append(k)
                except Exception:
                    pass
                self._cfg_snapshot = _new_snapshot
                # Always surface config changes to the terminal and log
                self._log(f"[CONFIG] Detected config update. Changed: {changed_keys if changed_keys else 'unknown'}")
        except Exception:
            pass
        portfolio = cfg.portfolio
        base_usd = float(portfolio.get("usd_per_trade", float(os.getenv("USD_NOTIONAL_PER_TRADE", "10000"))))
        usd_notional = float(self._alloc.get(symbol, base_usd))
        # Reserve a small cushion for round-trip fees
        fee_rate = float(cfg.raw.get("transaction_fee", 0.0))
        desired_usdt = max(0.0, usd_notional * (1.0 - 2.0 * fee_rate))
        # Cap by available USDT
        return min(desired_usdt, max(0.0, self._available_usdt()))

    def _available_usdt(self) -> float:
        """Free quote cash (USDT) on the broker; 0.0 when the balance cannot be read."""
        try:
            return float(self.broker.fetch_balance().get("free", {}).get(QUOTE, 0.0) or 0.0)
        except Exception:
            return 0.0

    def run_once(self) -> None:
        # At the start of each iteration, check for config and slow-stop flag changes
        # This ensures changes are picked up immediately (within one cycle)
        
        # 1. Check and reload config if changed
        config_changed = self.cfg_loader.reload_if_changed()
        if config_changed:
            self._log("[CONFIG] Config file reloaded - changes will take effect immediately")
            # Update rate limiter if rate limit changed
            try:
                new_rate = int(self.cfg_loader.get().rate_limit.get("orders_per_min", 15))
                if new_rate != self.rate_limiter.max_per_minute:
                    self.rate_limiter.max_per_minute = new_rate
                    self._log(f"[CONFIG] Rate limit updated to {new_rate} per minute")
            except Exception:
                pass
        
        cfg = self.cfg_loader.get()
        
        # 2. Check slow-stop status from config (checked on every iteration)
        slow_stop_status = self._slow_stop_enabled(cfg)
        if slow_stop_status != self._last_slow_stop_status:
            # Always log slow-stop status changes (important for user visibility)
            if slow_stop_status:
                self._log("[SLOW-STOP] Mode ENABLED: No new entries, but stop-loss and take-profit will continue")
            else:
                self._log("[SLOW-STOP] Mode DISABLED: Normal trading resumed")
            self._last_slow_stop_status = slow_stop_status
        # Single-coin mode: only process the configured symbol
        single_coin_mode = bool(cfg.portfolio.get("single_coin_mode", False))
        if single_coin_mode:
            single_coin_symbol = str(cfg.portfolio.get("single_coin_symbol", "BTC/USDT"))
            symbols = [single_coin_symbol]
        else:
            symbols = [s for s, enabled in cfg.crypto_list.items() if enabled]
        dash_status: Dict[str, Dict] = {"meta": {"ts": time.time(), "equity": None, "tf": None, "config": {}}}

        current_equity = self._fetch_equity()
        # Use last good equity if current fetch failed or returned invalid
        effective_equity = current_equity if (current_equity and current_equity > 0) else (self._last_good_equity or 0.0)
        # Compute guard equity (USD free + pack) for drawdown logic
        guard_equity, _guard_valid_now = self._guard_equity(symbols)
        # Daily peak reset using configured daily_check_time
        try:
            dct = str(cfg.portfolio.get("daily_check_time", "00:00"))
            hh, mm = [int(x) for x in dct.split(":", 1)]
        except Exception:
            hh, mm = 0, 0
        now_utc = time.gmtime()
        today_str = time.strftime("%Y-%m-%d", now_utc)
        crossed = (now_utc.tm_hour > hh) or (now_utc.tm_hour == hh and now_utc.tm_min >= mm)
        if crossed and self._last_peak_reset_date != today_str:
            # Reset both display peak and guard peak once after configured daily time
            self.peak_equity = float(effective_equity or self.peak_equity or 0.0)
            self._guard_peak = float(guard_equity or self._guard_peak or 0.0)
            self._last_peak_reset_date = today_str
            self._today = today_str
            self._guard_peak_date = today_str
            # Reset daily loss counters for new day
            if isinstance(self._daily_losses, dict):
                self._daily_losses[today_str] = {}
                os.makedirs("record", exist_ok=True)
                save_json(self._daily_loss_path, self._daily_losses)
            # Reset per-coin peak equity for pack allocation (will be re-initialized based on current equity)
            self._coin_peaks = {}
            os.makedirs("record", exist_ok=True)
            save_json(self._coin_peak_path, self._coin_peaks)
            # Reset per-coin daily drawdown state for all positions
            for symbol, pos in self.positions.items():
                if pos:
                    # Reset daily peak equity and date for per-coin drawdown tracking
                    pos.daily_peak_equity = None
                    pos.daily_date = today_str
                    if cfg.detail_console_output:
                        self._log(f"[DAILY-RESET] {symbol} per-coin drawdown reset: daily_peak_equity=None, daily_date={today_str}")
            if cfg.detail_console_output:
                self._log(f"[DAILY-RESET] Daily reset at {dct} UTC: peak_equity={self.peak_equity:.2f}, guard_peak={self._guard_peak:.2f}, daily_losses reset for {today_str}")
            # Persist the reset date to ensure future restarts don't miss it
            try:
                save_json(self._last_reset_path, {"date": today_str})
            except Exception:
                pass
            # Persist peaks for the new day
            try:
                save_json(self._peaks_path, {"date": today_str, "display_peak": self.peak_equity, "guard_peak": self._guard_peak})
            except Exception:
                pass
        else:
            # Update display peak using mark-to-market effective equity
            self.peak_equity, self._today = update_daily_peak(self.peak_equity, effective_equity, self._today)
            # Update guard peak separately
            self._guard_peak, self._guard_peak_date = update_daily_peak(self._guard_peak, guard_equity, self._guard_peak_date)
            # Persist updated peaks for today
            try:
                if self._today == today_str:
                    save_json(self._peaks_path, {"date": today_str, "display_peak": self.peak_equity, "guard_peak": self._guard_peak})
            except Exception:
                pass
        if current_equity and current_equity > 0:
            self._last_good_equity = current_equity
        # peak already updated by helper
        now_ts = time.time()
        if cfg.detail_console_output and (now_ts - self._last_console_summary_ts) >= 60.0:
            self._log(f"[INFO] Equity: {effective_equity:.2f} USDT | Peak: {self.peak_equity:.2f} USDT")
            self._last_console_summary_ts = now_ts
        # init dashboard meta
        dash_status["meta"]["equity"] = float(effective_equity or 0.0)

        # Update today's PnL + status summary file each cycle
        # Pass reset_time_utc to filter transactions after daily reset time
        # If reset happened today, only count trades after the reset time
        dct = str(cfg.portfolio.get("daily_check_time", "00:00"))
        reset_time_for_pnl = None
        if crossed and self._last_peak_reset_date == today_str:
            # Reset happened today, so filter transactions after reset time
            reset_time_for_pnl = dct
        fc_write_daily_pnl(
            "record",
            "record",
            self.cfg_loader,
            self._alloc,
            self.positions,
            detail_console_output=False,  # suppress repetitive terminal prints
            current_equity_usd=effective_equity,
            reset_time_utc=reset_time_for_pnl,
        )
        # Evaluate drawdown vs initial_equity using mark-to-market equity (does not penalize spending cash)
        dd_thresh = float(cfg.portfolio.get("max_drawdown", 0.1))
        dd_trigger = False
        entries_blocked = False  # a tripped guard stops new entries only; exits must keep running
        if self.initial_equity and self.initial_equity > 0 and effective_equity and effective_equity > 0:
            drop_ratio = max(0.0, (self.initial_equity - effective_equity) / self.initial_equity)
            dd_trigger = drop_ratio >= dd_thresh
        if dd_trigger:
            self._dd_breach_count += 1
            if self._dd_breach_count >= 3:  # require 3 consecutive cycles to trigger
                if cfg.detail_console_output:
                    self._log(f"[GUARD] Global drawdown exceeded ({drop_ratio*100:.1f}% >= {dd_thresh*100:.1f}%); blocking new entries this cycle")
                entries_blocked = True
        else:
            self._dd_breach_count = 0

        # Parallel fetch OHLCV for primary (always), higher timeframe (optional), and micro signals (optional)
        def fetch_pair(sym: str):
            try:
                sp = cfg.signal_portfolio
                tf_ltf = str(sp.get("ltf_timeframe", "1h"))
                use_htf = bool(sp.get("use_htf", True))
                tf_htf = str(sp.get("htf_timeframe", "4h"))
                use_micro = bool(sp.get("use_micro_signals", True))
                tf_micro = str(sp.get("micro_signals_timeframe", "1m"))
                now = time.time()
                last = float(self._last_fetch_ts.get(sym, 0.0))
                # enforce >=0.25s between fetches per symbol
                if (now - last) < 0.25 and sym in self._ohlcv_cache:
                    return sym, self._ohlcv_cache[sym]
                o1 = self.market_data.fetch_ohlcv(sym, timeframe=tf_ltf, limit=200)
                o2 = self.market_data.fetch_ohlcv(sym, timeframe=tf_htf, limit=200) if use_htf else None
                o_micro = self.market_data.fetch_ohlcv(sym, timeframe=tf_micro, limit=200) if use_micro else None
                result = (o1, o2, use_htf, o_micro, use_micro, tf_ltf)
                self._ohlcv_cache[sym] = result
                self._last_fetch_ts[sym] = now
                return sym, result
            except Exception:
                return sym, (None, None, False, None, False, None)

        ohlcvs = parallel_dict(fetch_pair, symbols, max_workers=min(8, len(symbols) or 1))

        for symbol in symbols:
            res = ohlcvs.get(symbol, (None, None, False, None, False, None))
            o1, o2, use_htf, o_micro, use_micro, tf_ltf = res
            if o1 is None:
                continue
            if dash_status["meta"].get("tf") is None and tf_ltf:
                dash_status["meta"]["tf"] = tf_ltf
                # Fill config summary once
                try:
                    sp = cfg.signal_portfolio
                    dash_status["meta"]["config"] = {
                        "source": str(cfg.raw.get("data", {}).get("source", "ccxt")),
                        "ltf_timeframe": str(sp.get("ltf_timeframe", "1h")),
                        "htf_timeframe": str(sp.get("htf_timeframe", "4h")),
                        "use_htf": bool(sp.get("use_htf", True)),
                        "use_micro_signals": bool(sp.get("use_micro_signals", True)),
                        "micro_signals_timeframe": str(sp.get("micro_signals_timeframe", "1m")),
                        "signals": {
                            "macd": bool(sp.get("macd", True)),
                            "rsi": bool(sp.get("rsi", True)),
                            "bb": bool(sp.get("bb", True)),
                            "volume": bool(sp.get("volume", True)),
                            "price": bool(sp.get("price", True)),
                            "engulfing": bool(sp.get("engulfing", True)),
                            "ob_imbalance": bool(sp.get("ob_imbalance", False)),
                            "ob_depth": bool(sp.get("ob_depth", False)),
                            "ob_pressure": bool(sp.get("ob_pressure", False)),
                            "ob_large_orders": bool(sp.get("ob_large_orders", False)),
                        },
                    }
                except Exception:
                    pass
            # If allocation override explicitly zero -> skip symbol from pack
            if float(self._alloc.get(symbol, 1.0)) == 0.0:
                continue
            ind = compute_indicators(o1, cfg.signal_portfolio)
            # HTF indicator computation with error handling and diagnostics
            if use_htf and o2 is not None:
                try:
                    ind_htf = compute_indicators(o2, cfg.signal_portfolio)
                    if cfg.detail_console_output and ind_htf is not None:
                        macd_len = len(ind_htf.get("macd", []))
                        if macd_len < 35:
                            self._log(f"[HTF-DEBUG] {symbol} HTF indicators computed but insufficient data: {macd_len} < 35 candles")
                except Exception as e:
                    if cfg.detail_console_output:
                        self._log(f"[HTF-DEBUG] {symbol} HTF indicator computation error: {type(e).__name__}: {e}")
                    ind_htf = None
            else:
                if use_htf and o2 is None and cfg.detail_console_output:
                    self._log(f"[HTF-DEBUG] {symbol} HTF data fetch returned None (o2 is None)")
                ind_htf = None
            # If using micro signals, replace RSI/BB/Volume/Close from micro timeframe
            if use_micro and o_micro is not None:
                ind_micro = compute_indicators(o_micro, cfg.signal_portfolio)
                for k in ["rsi", "bb_upper", "bb_lower", "bb_mid", "volume", "vol_ma20", "close"]:
                    ind[k] = ind_micro[k]
            price = float(ind["close"].iloc[-1])
            
            # Fetch order book data if any order book signals are enabled
            orderbook = None
            ob_config = cfg.raw.get('orderbook_signals', {})
            sp = cfg.signal_portfolio
            has_ob_signals = bool(sp.get("ob_imbalance", False) or sp.get("ob_depth", False) or 
                                 sp.get("ob_pressure", False) or sp.get("ob_large_orders", False))
            
            if has_ob_signals:
                try:
                    orderbook = self.market_data.fetch_order_book(symbol, limit=20)
                except Exception:
                    orderbook = None
            
            # Compute statuses once and store
            statuses = self._signal_statuses(ind, cfg.signal_portfolio, orderbook, price, ob_config)
            # Get pack allocation, max loss, and holding time for this symbol
            base_usd = float(cfg.portfolio.get("usd_per_trade", 10000.0))
            pack_allocation = float(self._alloc.get(symbol, base_usd))
            max_loss = float(cfg.portfolio.get("per_crypto_max_drawdown", 1000))
            max_holding_time = int(cfg.portfolio.get("maximum_holding_time", 259200))
            
            dash_status[symbol] = {
                "rsi": bool(statuses.get("rsi", True)),
                "bb": bool(statuses.get("bb", True)),
                "macd": bool(statuses.get("macd", True)),
                "volume": bool(statuses.get("volume", True)),
                "price": bool(statuses.get("price", True)),
                "engulfing": bool(statuses.get("engulfing", True)),
                "ob_imbalance": bool(statuses.get("ob_imbalance", False)),
                "ob_depth": bool(statuses.get("ob_depth", False)),
                "ob_pressure": bool(statuses.get("ob_pressure", False)),
                "ob_large_orders": bool(statuses.get("ob_large_orders", False)),
                "close": price,
                "pack_allocation": pack_allocation,
                "max_loss": max_loss,
                "max_holding_time": max_holding_time,
            }

            pos = self.positions.get(symbol)
            # Mark as not on hold if no position, and clear position fields
            if not pos:
                dash_status[symbol]["on_hold"] = False
                # Clear position fields when no position exists
                dash_status[symbol].pop("entry", None)
                dash_status[symbol].pop("qty", None)
                dash_status[symbol].pop("stop", None)
                dash_status[symbol].pop("next_tp", None)
                dash_status[symbol].pop("value", None)
                dash_status[symbol].pop("unrealized_pnl", None)
            if pos:
                # Daily per-coin max drawdown (resets at daily_check_time)
                # Check peak-to-trough drawdown, offset with realized PnL (gains reduce loss, losses add to loss)
                cap = float(cfg.portfolio.get("per_crypto_max_drawdown", 1000))
                current_equity = float(price * pos.quantity)
                # Initialize daily_peak_equity if None (after daily reset or first check)
                if getattr(pos, "daily_peak_equity", None) is None:
                    pos.daily_peak_equity = current_equity
                # Initialize daily_date if not set (after daily reset or first check)
                if getattr(pos, "daily_date", "") != self._today:
                    pos.daily_date = self._today
                peak_equity = float(getattr(pos, "daily_peak_equity", current_equity) or current_equity)
                if current_equity > peak_equity:
                    pos.daily_peak_equity = current_equity
                    peak_equity = current_equity
                peak_to_trough_loss = max(0.0, peak_equity - current_equity)
                
                # Update persistent peak equity for pack allocation
                try:
                    self._coin_peaks = load_json(self._coin_peak_path) or {}
                    stored_peak = float(self._coin_peaks.get(symbol, {}).get("peak_equity", peak_equity) or peak_equity)
                    stored_date = str(self._coin_peaks.get(symbol, {}).get("date", "") or "")
                    # Reset peak if date changed
                    if stored_date != self._today:
                        stored_peak = current_equity
                        stored_date = self._today
                    # Update peak if current is higher
                    if current_equity > stored_peak:
                        stored_peak = current_equity
                    # Update stored peak
                    if symbol not in self._coin_peaks:
                        self._coin_peaks[symbol] = {}
                    self._coin_peaks[symbol]["peak_equity"] = stored_peak
                    self._coin_peaks[symbol]["date"] = stored_date
                    save_json(self._coin_peak_path, self._coin_peaks)
                    
                    # Update pack allocation based on peak-to-trough drawdown
                    # Pack should reduce on loss, increase on new peak
                    # The gap between peak and current should not exceed max_loss_cap
                    self._alloc = load_json(self._alloc_path) or {}
                    portfolio = cfg.portfolio
                    base_usd = float(portfolio.get("usd_per_trade", float(os.getenv("USD_NOTIONAL_PER_TRADE", "10000"))))
                    max_loss_cap = float(portfolio.get("per_crypto_max_drawdown", 1000))
                    current_alloc = float(self._alloc.get(symbol, base_usd))
                    
                    # Calculate loss from stored peak
                    loss_from_peak = max(0.0, stored_peak - current_equity)
                    # Cap the loss at max_loss_cap
                    capped_loss = min(loss_from_peak, max_loss_cap)
                    
                    # Pack allocation = peak_equity - capped_loss
                    # This ensures pack reduces on loss and increases on new peak
                    new_alloc = max(0.0, stored_peak - capped_loss)
                    
                    # Only update if allocation changed significantly (avoid constant writes)
                    if abs(new_alloc - current_alloc) > 0.01:
                        self._alloc[symbol] = new_alloc
                        save_json(self._alloc_path, self._alloc)
                        if cfg.detail_console_output:
                            self._log(f"[PACK] {symbol} pack updated: ${current_alloc:.2f} -> ${new_alloc:.2f} (Peak: ${stored_peak:.2f}, Current: ${current_equity:.2f}, Loss: ${loss_from_peak:.2f}, Capped: ${capped_loss:.2f})")
                except Exception as e:
                    if cfg.detail_console_output:
                        self._log(f"[PACK-ERROR] Failed to update pack for {symbol}: {e}")
                
                # Calculate net loss: unrealized loss + realized losses OR unrealized loss - realized gains
                # This ensures gains offset losses and losses add together
                try:
                    self._daily_losses = load_json(self._daily_loss_path) or {}
                    day_losses = (self._daily_losses or {}).get(self._today, {})
                    realized_net_pnl = float(day_losses.get(symbol, 0.0) or 0.0)
                    # Net loss calculation:
                    # - If realized_net_pnl is positive (gains): offset unrealized loss
                    # - If realized_net_pnl is negative (losses): add to unrealized loss
                    # Formula: peak_to_trough_loss - realized_net_pnl
                    #   If realized_net_pnl > 0 (gains): reduces the loss
                    #   If realized_net_pnl < 0 (losses): increases the loss (double negative = positive)
                    net_loss_after_gains = max(0.0, peak_to_trough_loss - realized_net_pnl)
                except Exception:
                    net_loss_after_gains = peak_to_trough_loss
                
                if net_loss_after_gains >= cap:
                    # Calculate liquidation details for logging
                    loss_usdt = net_loss_after_gains
                    
                    # Log liquidation event
                    log_liquidation(
                        "record",
                        pair=symbol,
                        current_price=price,
                        quantity=pos.quantity,
                        peak_equity=peak_equity,
                        current_equity=current_equity,
                        loss_usdt=loss_usdt,
                        reason="daily_max_drawdown"
                    )
                    
                    if cfg.detail_console_output:
                        self._log(f"[STOP] Daily per-coin max loss exceeded for {symbol}; closing position (Peak: ${peak_equity:.2f}, Current: ${current_equity:.2f}, Peak-to-trough: ${peak_to_trough_loss:.2f}, Realized PnL: ${realized_net_pnl:.2f}, Net loss: ${loss_usdt:.2f})")
                    st, _ = self._submit_sell(symbol, price, pos.quantity)
                    if st == "FILLED":
                        self._on_trade_closed(symbol, pos, price)
                        del self.positions[symbol]
                    else:
                        self._log(f"[WARN] SELL not confirmed filled for {symbol} on daily max loss stop (status={st or 'UNKNOWN'})")
                    # Set allocation to 0 to remove from coin packing
                    self._alloc[symbol] = 0.0
                    save_json(self._alloc_path, self._alloc)
                    continue
                # Immediate stop-loss breach check (hard stop)
                try:
                    stop_px = float(pos.stop_price or 0.0)
                except Exception:
                    stop_px = 0.0
                if stop_px > 0 and price <= stop_px:
                    if cfg.detail_console_output:
                        self._log(f"[STOP] Stop-loss breached for {symbol}: last={price:.4f} stop={stop_px:.4f}; exiting")
                    st, _ = self._submit_sell(symbol, price, pos.quantity)
                    if st == "FILLED":
                        self._on_trade_closed(symbol, pos, price)
                        del self.positions[symbol]
                    else:
                        self._log(f"[WARN] SELL not confirmed filled for {symbol} on hard stop (status={st or 'UNKNOWN'})")
                    # Do not alter allocation here; dynamic rotation logic handles it elsewhere
                    continue
                if should_liquidate_by_age(pos.opened_ts, int(cfg.portfolio.get("maximum_holding_time", 259200))):
                    if cfg.detail_console_output:
                        self._log(f"[EOD] Max hold time reached for {symbol}; closing position")
                    st, _ = self._submit_sell(symbol, price, pos.quantity)
                    if st == "FILLED":
                        self._on_trade_closed(symbol, pos, price)
                        del self.positions[symbol]
                    else:
                        self._log(f"[WARN] SELL not confirmed filled for {symbol} on max holding close (status={st or 'UNKNOWN'})")
                    # rotation cooldown hours (default 24)
                    # rotation cooldown hours (default 24)
                    cooldown_hours = float(os.getenv("ROTATION_COOLDOWN_HOURS", "24"))
                    self._cooldown[symbol] = time.time() + cooldown_hours * 3600.0
                    save_json(self._cooldown_path, self._cooldown)
                    # Add freed capital to spare and remove symbol from pack (no rotation)
                    freed_usd = float(price * pos.quantity)
                    self._alloc = fc_persist_rotation(
                        self._alloc_path,
                        self._alloc,
                        symbol,
                        freed_usd,
                        dest_symbols=[],
                        weights=None,
                        cfg_loader=self.cfg_loader,
                    )
                    continue
                action = evaluate_dynamic_sl_tp(
                    pos,
                    price,
                    cfg.stop_loss_take_gain,
                    bb_lower=float(ind["bb_lower"].iloc[-1]),
                    bb_upper=float(ind["bb_upper"].iloc[-1]),
                    rsi_value=float(ind["rsi"].iloc[-1]),
                    macd_bearish_div=macd_bearish_divergence(ind),
                    fee_rate=float(cfg.raw.get("transaction_fee", 0.0)),
                )
                if action["action"] == "exit":
                    if cfg.detail_console_output:
                        self._log(f"[EXIT] Exit triggered for {symbol}")
                    st, _ = self._submit_sell(symbol, price, pos.quantity)
                    if st == "FILLED":
                        self._on_trade_closed(symbol, pos, price)
                        del self.positions[symbol]
                    else:
                        self._log(f"[WARN] SELL not confirmed filled for {symbol} on exit (status={st or 'UNKNOWN'})")
                elif action["action"] == "partial_take":
                    # Use original_quantity for sell calculation, not current quantity
                    # This ensures each level sells the correct percentage of the original buy-in
                    original_qty = getattr(pos, "original_quantity", None) or pos.quantity
                    qty = original_qty * float(action["sell_fraction"])
                    if qty > 0:
                        if cfg.detail_console_output:
                            self._log(f"[TP] Partial take-profit {qty:.6f} {symbol} (from original {original_qty:.6f}, {float(action['sell_fraction'])*100:.0f}%)")
                        st, _ = self._submit_sell(symbol, price, qty)
                        if st == "FILLED":
                            pos.quantity -= qty
                        else:
                            self._log(f"[WARN] PARTIAL SELL not confirmed filled for {symbol} (status={st or 'UNKNOWN'})")
                        pos.stop_price = float(action.get("new_stop") or pos.stop_price)
                        # Record highest tier reached (non-regressive: only increases, never decreases)
                        try:
                            pos.highest_tier_reached = max(int(getattr(pos, "highest_tier_reached", 0) or 0), int(action.get("tier") or 0))
                        except Exception:
                            pass
                else:
                    pos.stop_price = float(action.get("new_stop") or pos.stop_price)
                    # Maintain non-regressive tier state on hold
                    try:
                        pos.highest_tier_reached = max(int(getattr(pos, "highest_tier_reached", 0) or 0), int(action.get("tier") or 0))
                    except Exception:
                        pass
                # Show holding info each cycle for this coin
                if cfg.detail_console_output:
                    unreal = (price - pos.avg_price) * pos.quantity
                    # compute next TP level if dynamic mode on
                    next_tp_str = "-"
                    try:
                        sltg = cfg.stop_loss_take_gain
                        if bool(sltg.get("dynamic", True)):
                            entry = float(pos.entry_price or pos.avg_price or 0.0)
                            tiers = []
                            for i in ("1","2","3"):
                                tg = sltg.get(f"{i}_take_gain")
                                if tg is not None:
                                    tiers.append(entry * (1.0 + float(tg)))
                            nxt = None
                            for tp in sorted(tiers):
                                if price < tp:
                                    nxt = tp
                                    break
                            if nxt is not None:
                                next_tp_str = f"{nxt:.4f}"
                    except Exception:
                        pass
                    self._log(f"[HOLD] {symbol} qty={pos.quantity:.6f} entry={pos.entry_price:.4f} last={price:.4f} stop={(pos.stop_price if pos.stop_price else 0):.4f} nextTP={next_tp_str} unreal={unreal:.2f}")
                # record into dashboard status
                try:
                    entry_price = float(pos.entry_price or pos.avg_price or 0.0)
                    # Calculate unrealized PnL (gross - estimated exit fees)
                    entry_notional = entry_price * pos.quantity
                    current_notional = price * pos.quantity
                    gross_unreal = current_notional - entry_notional
                    # Estimate exit fees (only on exit, so we don't deduct here, but show gross)
                    unrealized_pnl = gross_unreal  # Will deduct fees on exit
                    dash_status[symbol]["on_hold"] = True
                    dash_status[symbol]["stop"] = float(pos.stop_price or 0.0)
                    dash_status[symbol]["qty"] = float(pos.quantity)
                    dash_status[symbol]["entry"] = entry_price
                    dash_status[symbol]["value"] = float((pos.quantity or 0.0) * price)
                    dash_status[symbol]["unrealized_pnl"] = float(unrealized_pnl)
                    # Add pack allocation, max loss, and holding time
                    base_usd = float(cfg.portfolio.get("usd_per_trade", 10000.0))
                    dash_status[symbol]["pack_allocation"] = float(self._alloc.get(symbol, base_usd))
                    dash_status[symbol]["max_loss"] = float(cfg.portfolio.get("per_crypto_max_drawdown", 1000))
                    dash_status[symbol]["max_holding_time"] = int(cfg.portfolio.get("maximum_holding_time", 259200))
                    # Calculate holding time for this position
                    if hasattr(pos, 'entry_timestamp') and pos.entry_timestamp:
                        holding_time_seconds = int(time.time()) - int(pos.entry_timestamp)
                        dash_status[symbol]["holding_time"] = holding_time_seconds
                    else:
                        dash_status[symbol]["holding_time"] = 0
                    # next TP as above
                    sltg = cfg.stop_loss_take_gain
                    entry = entry_price
                    next_tp_val = None
                    if bool(sltg.get("dynamic", True)) and entry > 0:
                        tiers = []
                        for i in ("1","2","3"):
                            tg = sltg.get(f"{i}_take_gain")
                            if tg is not None:
                                tiers.append(entry * (1.0 + float(tg)))
                        for tp in sorted(tiers):
                            if price < tp:
                                next_tp_val = tp
                                break
                    dash_status[symbol]["next_tp"] = float(next_tp_val) if next_tp_val else None
                except Exception:
                    pass
                continue

            # Skip if symbol in cooldown rotation
            cd_exp = float(self._cooldown.get(symbol, 0))
            if cd_exp and time.time() < cd_exp:
                continue

            # All enabled LTF signals confirmed AND HTF MACD bullish AND not in slow-stop
            if not use_htf:
                htf_ok = True
            else:
                if ind_htf is None:
                    htf_ok = False
                    if cfg.detail_console_output:
                        self._log(f"[HTF-DEBUG] {symbol} htf_ok=False: ind_htf is None")
                else:
                    try:
                        macd_result = macd_bullish(ind_htf)
                        htf_ok = bool(macd_result)
                        if not htf_ok and cfg.detail_console_output:
                            # Detailed diagnostics for why MACD is not bullish
                            macd_len = len(ind_htf.get("macd", []))
                            if macd_len < 35:
                                self._log(f"[HTF-DEBUG] {symbol} htf_ok=False: insufficient HTF data ({macd_len} < 35 candles)")
                            else:
                                macd_now = ind_htf["macd"].iloc[-1]
                                macd_sig = ind_htf["macd_signal"].iloc[-1]
                                hist = ind_htf["macd_hist"]
                                hist_last = hist.iloc[-3:]
                                hist_diff = hist_last.diff().dropna()
                                above_signal = float(macd_now) > float(macd_sig)
                                hist_inc = bool(len(hist_diff) >= 2 and hist_diff.iloc[-1] > 0 and hist_diff.iloc[-2] > 0) if len(hist_diff) >= 2 else bool(len(hist_diff) >= 1 and hist_diff.iloc[-1] > 0)
                                self._log(f"[HTF-DEBUG] {symbol} htf_ok=False: above_signal={above_signal}, hist_increasing={hist_inc}, macd={macd_now:.6f}, signal={macd_sig:.6f}")
                    except Exception as e:
                        htf_ok = False
                        if cfg.detail_console_output:
                            self._log(f"[HTF-DEBUG] {symbol} htf_ok=False: MACD check error: {type(e).__name__}: {e}")
            # Use entry_mode from config: "all" or "any_two"
            enabled_keys = [k for k in SIGNAL_KEYS if bool(cfg.signal_portfolio.get(k, True))]
            sig_ok = entry_signal_ok(dash_status[symbol], cfg.signal_portfolio)
            
            # Track blocking reasons
            blocking_reasons = []
            
            # Check cooldown
            cd_exp = float(self._cooldown.get(symbol, 0))
            if cd_exp and time.time() < cd_exp:
                remaining = int(cd_exp - time.time())
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                blocking_reasons.append(f"Cooldown ({hours}h {minutes}m)")
            
            # Check slow-stop
            if slow_stop_status:
                blocking_reasons.append("Slow-stop")
            
            # Check HTF
            if use_htf and not htf_ok:
                blocking_reasons.append("HTF not OK")
            
            # Check signals
            if not sig_ok:
                blocking_reasons.append("Signals not OK")
            
            # Update blocking reasons in dash_status
            dash_status[symbol]["blocking_reasons"] = blocking_reasons
            dash_status[symbol]["is_blocked"] = len(blocking_reasons) > 0
            
            # Use the current slow-stop status (checked at start of each symbol iteration)
            entry_ok = (not slow_stop_status) and sig_ok and htf_ok and not entries_blocked
            if not entry_ok and cfg.detail_console_output:
                failed = [k for k in SIGNAL_KEYS if k in enabled_keys and not dash_status[symbol].get(k, True)]
                passed = [k for k in SIGNAL_KEYS if k in enabled_keys and dash_status[symbol].get(k, False)]
                slow_stop_msg = " (slow-stop enabled)" if slow_stop_status else ""
                self._log(f"[CHECK] {symbol} entry blocked. passed={passed} failed={failed} htf_ok={htf_ok}{slow_stop_msg}")
            if entry_ok:
                # Enforce daily per-coin net loss cap (skip new entries)
                # Net loss = losses - gains (gains offset losses)
                try:
                    # Reload daily losses from disk to pick up any resets
                    self._daily_losses = load_json(self._daily_loss_path) or {}
                    cap = float(cfg.portfolio.get("per_crypto_max_drawdown", 1000))
                    day_losses = (self._daily_losses or {}).get(self._today, {})
                    net_pnl = float(day_losses.get(symbol, 0.0) or 0.0)
                    # Only check loss cap if net PnL is negative (net loss)
                    net_loss = abs(min(0.0, net_pnl))  # Convert negative PnL to positive loss
                    if net_loss >= cap:
                        # Update blocking reasons
                        if "blocking_reasons" not in dash_status[symbol]:
                            dash_status[symbol]["blocking_reasons"] = []
                        dash_status[symbol]["blocking_reasons"].append(f"Daily loss cap (${net_loss:.2f})")
                        dash_status[symbol]["is_blocked"] = True
                        if cfg.detail_console_output:
                            self._log(f"[DAILY-STOP] {symbol} reached daily loss cap; blocking new entries today (Net loss: ${net_loss:.2f} >= Cap: ${cap:.2f}, Net PnL: ${net_pnl:.2f})")
                        continue
                    elif net_loss > 0 and cfg.detail_console_output:
                        # Log when approaching the cap (optional, for debugging)
                        if net_loss >= cap * 0.8:  # Log when at 80% of cap
                            self._log(f"[DAILY-STOP] {symbol} approaching daily loss cap (Net loss: ${net_loss:.2f} / Cap: ${cap:.2f}, Net PnL: ${net_pnl:.2f})")
                except Exception as e:
                    if cfg.detail_console_output:
                        self._log(f"[WARN] Error checking daily loss cap for {symbol}: {e}")
                    pass
                # Optional micro-timeframe execution filter
                exec_cfg = cfg.raw.get("execution_filter", {})
                if bool(exec_cfg.get("enabled", True)):
                    micro_tf = str(exec_cfg.get("timeframe", "5m"))
                    try:
                        o_exec = self.market_data.fetch_ohlcv(symbol, timeframe=micro_tf, limit=200)
                        if not o_exec or not basic_execution_ok(o_exec, cfg.signal_portfolio):
                            if cfg.detail_console_output:
                                self._log(f"[EXEC-FILTER] {symbol} blocked by micro TF filter {micro_tf}")
                            continue
                    except Exception:
                        # If exec filter fails, skip this symbol for safety
                        continue
                
                # Momentum execution filter (blocks entry if momentum is not sustained)
                if bool(exec_cfg.get("momentum_enabled", True)):
                    try:
                        if not momentum_execution_ok(ind):
                            if cfg.detail_console_output:
                                self._log(f"[EXEC-FILTER] {symbol} blocked by momentum filter (momentum not sustained)")
                            continue
                    except Exception:
                        # If momentum filter fails, allow entry (fail open)
                        pass
                
                # Iceberg order execution filter (blocks entry if iceberg patterns detected)
                if bool(exec_cfg.get("iceberg_enabled", True)):
                    try:
                        order_book = self.market_data.fetch_order_book(symbol, limit=20)
                        iceberg_cfg = exec_cfg.get("iceberg", {})
                        if not iceberg_execution_ok(order_book, symbol, iceberg_cfg):
                            if cfg.detail_console_output:
                                self._log(f"[EXEC-FILTER] {symbol} blocked by iceberg filter (market manipulation detected)")
                            continue
                    except Exception:
                        # If iceberg filter fails, allow entry (fail open)
                        pass
                
                usdt = self._usdt_for_trade(symbol)
                amount = usdt / price if price > 0 else 0
                if amount > 0:
                    # Capture which indicators were triggered for this buy
                    signals = {
                        "rsi": dash_status[symbol].get("rsi", False),
                        "bb": dash_status[symbol].get("bb", False),
                        "macd": dash_status[symbol].get("macd", False),
                        "volume": dash_status[symbol].get("volume", False),
                        "price": dash_status[symbol].get("price", False),
                        "engulfing": dash_status[symbol].get("engulfing", False),
                        "ob_imbalance": dash_status[symbol].get("ob_imbalance", False),
                        "ob_depth": dash_status[symbol].get("ob_depth", False),
                        "ob_pressure": dash_status[symbol].get("ob_pressure", False),
                        "ob_large_orders": dash_status[symbol].get("ob_large_orders", False),
                    }
                    if cfg.detail_console_output:
                        self._log(f"[ENTRY] BUY {symbol} amount={amount:.6f} at {price:.6f}")
                    self._submit_buy(symbol, price, amount, signals=signals)

        # Persist dashboard status (merge with previous to avoid blanking on transient failures)
        try:
            prev = {}
            try:
                with open(self._dash_status_path, 'r', encoding='utf-8') as f:
                    import json as _json
                    prev = _json.load(f)
            except Exception:
                prev = {}
            # Merge per-symbol only if we computed it this loop
            merged = prev if isinstance(prev, dict) else {}
            merged_meta = merged.get("meta", {})
            merged_meta.update(dash_status.get("meta", {}))
            merged["meta"] = merged_meta
            for k, v in dash_status.items():
                if k == "meta":
                    continue
                # Preserve position fields (entry, qty, stop, next_tp) from previous data if not in new data
                # BUT only if on_hold is True (position still exists)
                prev_symbol = merged.get(k, {})
                if isinstance(prev_symbol, dict) and isinstance(v, dict):
                    # Only preserve position fields if on_hold is True (position exists)
                    # If on_hold is False, clear position fields
                    on_hold = v.get("on_hold", False)
                    if on_hold:
                        # Preserve position fields if they exist in previous but not in new
                        position_fields = ["entry", "qty", "stop", "next_tp", "value", "unrealized_pnl"]
                        for field in position_fields:
                            if field in prev_symbol and field not in v:
                                v[field] = prev_symbol[field]
                    else:
                        # Clear position fields when on_hold is False
                        position_fields = ["entry", "qty", "stop", "next_tp", "value", "unrealized_pnl"]
                        for field in position_fields:
                            v.pop(field, None)
                merged[k] = v
            # Only write if we have at least one symbol updated
            updated_symbols = [k for k in dash_status.keys() if k != "meta"]
            if updated_symbols:
                os.makedirs("record", exist_ok=True)
                save_json(self._dash_status_path, merged)
        except Exception:
            pass

    def _slow_stop_enabled(self, cfg=None) -> bool:
        """Check if slow-stop mode is enabled from config.
        
        Args:
            cfg: Optional config object. If None, will fetch from cfg_loader.
        
        Returns:
            True if slow-stop is enabled, False otherwise.
        """
        if cfg is None:
            cfg = self.cfg_loader.get()
        
        # Read slow-stop from config.yaml (runtime.slow_stop)
        runtime = cfg.raw.get("runtime", {})
        return bool(runtime.get("slow_stop", False))

    def _log(self, message: str) -> None:
        import logging
        # Single-path logging: rely on configured handlers (file + console).
        # Avoid duplicate prints to keep one-line-per-event formatting.
        logging.info(message)

    def _submit_buy(self, symbol: str, price: float, amount: float, signals: Optional[Dict[str, bool]] = None) -> None:
        # Enforce min notional ~ 1 USD
        if price * amount < 1.0:
            return
        try:
            order = self.broker.place_market_order(symbol, "BUY", amount)
        except Exception:
            order = None
        order_id = (order.id or None) if order is not None else None
        status = order.status.upper() if order is not None else None
        log_order("record", pair=symbol, side="BUY", price=price, quantity=amount, order_id=order_id, signals=signals)
        # Confirm fill: retry query_order a few times for market fills
        # Without an order id there is nothing to confirm: the order stays unconfirmed.
        if status != "FILLED" and order_id:
            for _ in range(3):
                try:
                    time.sleep(0.5)
                    status = self.broker.query_order(order_id, symbol).status.upper() or status
                    if status == "FILLED":
                        break
                except Exception:
                    continue
        # Only create a position on confirmed FILLED
        if status == "FILLED":
            self.positions[symbol] = Position(
                symbol=symbol, 
                quantity=amount, 
                avg_price=price, 
                entry_price=price,
                original_quantity=amount  # Store original buy-in quantity for take-profit calculations
            )
            # Initialize peak equity and update pack allocation
            try:
                cfg = self.cfg_loader.get()
                current_equity = float(price * amount)
                self._coin_peaks = load_json(self._coin_peak_path) or {}
                stored_peak = float(self._coin_peaks.get(symbol, {}).get("peak_equity", current_equity) or current_equity)
                stored_date = str(self._coin_peaks.get(symbol, {}).get("date", "") or "")
                # Reset peak if date changed
                if stored_date != self._today:
                    stored_peak = current_equity
                    stored_date = self._today
                # Update peak if current is higher
                if current_equity > stored_peak:
                    stored_peak = current_equity
                # Update stored peak
                if symbol not in self._coin_peaks:
                    self._coin_peaks[symbol] = {}
                self._coin_peaks[symbol]["peak_equity"] = stored_peak
                self._coin_peaks[symbol]["date"] = stored_date
                save_json(self._coin_peak_path, self._coin_peaks)
                
                # Update pack allocation based on peak-to-trough drawdown
                self._alloc = load_json(self._alloc_path) or {}
                portfolio = cfg.portfolio
                base_usd = float(portfolio.get("usd_per_trade", float(os.getenv("USD_NOTIONAL_PER_TRADE", "10000"))))
                max_loss_cap = float(portfolio.get("per_crypto_max_drawdown", 1000))
                
                # Calculate loss from stored peak
                loss_from_peak = max(0.0, stored_peak - current_equity)
                # Cap the loss at max_loss_cap
                capped_loss = min(loss_from_peak, max_loss_cap)
                
                # Pack allocation = peak_equity - capped_loss
                current_alloc = float(self._alloc.get(symbol, base_usd))
                new_alloc = max(0.0, stored_peak - capped_loss)
                
                if abs(new_alloc - current_alloc) > 0.01:
                    self._alloc[symbol] = new_alloc
                    save_json(self._alloc_path, self._alloc)
                    if cfg.detail_console_output:
                        self._log(f"[PACK] {symbol} pack updated on open: ${current_alloc:.2f} -> ${new_alloc:.2f} (Peak: ${stored_peak:.2f}, Current: ${current_equity:.2f}, Loss: ${loss_from_peak:.2f}, Capped: ${capped_loss:.2f})")
            except Exception as e:
                if cfg.detail_console_output:
                    self._log(f"[PACK-ERROR] Failed to update pack for {symbol} on open: {e}")
        else:
            # Surface a warning when order not confirmed filled
            self._log(f"[WARN] BUY not confirmed filled for {symbol} (status={status or 'UNKNOWN'})")

    def _submit_sell(self, symbol: str, price: float, amount: float) -> tuple[str | None, str | None]:
        if price * amount < 1.0:
            return None, None
        try:
            order = self.broker.place_market_order(symbol, "SELL", amount)
        except Exception:
            order = None
        order_id = (order.id or None) if order is not None else None
        status = order.status.upper() if order is not None else None
        log_order("record", pair=symbol, side="SELL", price=price, quantity=amount, order_id=order_id)
        # Confirm sell fill (best-effort)
        # Without an order id there is nothing to confirm: the order stays unconfirmed.
        if status != "FILLED" and order_id:
            for _ in range(3):
                try:
                    time.sleep(0.5)
                    status = self.broker.query_order(order_id, symbol).status.upper() or status
                    if status == "FILLED":
                        break
                except Exception:
                    continue
        return status, order_id
    

    def _on_trade_closed(self, symbol: str, pos: Position, exit_price: float) -> None:
        # Net PnL after transaction fees (applied on buy and sell notionals)
        cfg = self.cfg_loader.get()
        fee_rate = float(cfg.raw.get("transaction_fee", 0.0))
        entry_notional = pos.avg_price * pos.quantity
        exit_notional = exit_price * pos.quantity
        gross = exit_notional - entry_notional
        fees = fee_rate * entry_notional + fee_rate * exit_notional
        pnl_usdt = gross - fees
        pnl_pct = (((exit_price - pos.avg_price) / pos.avg_price) - 2.0 * fee_rate) * 100.0 if pos.avg_price else None
        log_trade_close("record", pair=symbol, entry_price=pos.avg_price, exit_price=exit_price, quantity=pos.quantity, pnl_pct=pnl_pct)

        # Update coin pack allocation based on peak-to-trough drawdown
        # Pack should reduce on loss, increase on new peak
        # The gap between peak and current should not exceed max_loss_cap
        try:
            # Calculate final equity at close
            final_equity = float(exit_price * pos.quantity)
            
            # Reload peak equity and allocation from disk
            self._coin_peaks = load_json(self._coin_peak_path) or {}
            self._alloc = load_json(self._alloc_path) or {}
            portfolio = cfg.portfolio
            base_usd = float(portfolio.get("usd_per_trade", float(os.getenv("USD_NOTIONAL_PER_TRADE", "10000"))))
            max_loss_cap = float(portfolio.get("per_crypto_max_drawdown", 1000))
            
            # Get stored peak equity
            stored_peak = float(self._coin_peaks.get(symbol, {}).get("peak_equity", final_equity) or final_equity)
            stored_date = str(self._coin_peaks.get(symbol, {}).get("date", "") or "")
            
            # Reset peak if date changed
            if stored_date != self._today:
                stored_peak = final_equity
                stored_date = self._today
            
            # Update peak if final equity is higher
            if final_equity > stored_peak:
                stored_peak = final_equity
            
            # Update stored peak
            if symbol not in self._coin_peaks:
                self._coin_peaks[symbol] = {}
            self._coin_peaks[symbol]["peak_equity"] = stored_peak
            self._coin_peaks[symbol]["date"] = stored_date
            save_json(self._coin_peak_path, self._coin_peaks)
            
            # Calculate loss from stored peak
            loss_from_peak = max(0.0, stored_peak - final_equity)
            # Cap the loss at max_loss_cap
            capped_loss = min(loss_from_peak, max_loss_cap)
            
            # Pack allocation = peak_equity - capped_loss
            # This ensures pack reduces on loss and increases on new peak
            current_alloc = float(self._alloc.get(symbol, base_usd))
            new_alloc = max(0.0, stored_peak - capped_loss)
            
            self._alloc[symbol] = new_alloc
            save_json(self._alloc_path, self._alloc)
            if cfg.detail_console_output:
                self._log(f"[PACK] {symbol} pack updated on close: ${current_alloc:.2f} -> ${new_alloc:.2f} (Peak: ${stored_peak:.2f}, Final: ${final_equity:.2f}, Loss: ${loss_from_peak:.2f}, Capped: ${capped_loss:.2f}, PnL: ${pnl_usdt:.2f})")
        except Exception as e:
            if cfg.detail_console_output:
                self._log(f"[PACK-ERROR] Failed to update pack for {symbol} on close: {e}")

        # Accumulate daily net PnL per coin (gains offset losses)
        # Reload from disk first to ensure we have latest data after reset
        try:
            # Reload daily losses from disk to pick up any resets
            self._daily_losses = load_json(self._daily_loss_path) or {}
            today = self._today
            if isinstance(self._daily_losses, dict):
                if today not in self._daily_losses:
                    self._daily_losses[today] = {}
                # Track net PnL: gains offset losses
                # Positive values = net gains, negative values = net losses
                current_net_pnl = float(self._daily_losses[today].get(symbol, 0.0) or 0.0)
                new_net_pnl = current_net_pnl + pnl_usdt  # Add PnL (can be positive or negative)
                self._daily_losses[today][symbol] = new_net_pnl
                os.makedirs("record", exist_ok=True)
                save_json(self._daily_loss_path, self._daily_losses)
        except Exception:
            pass

    


def main(argv: Optional[list[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m bot.trader", description="Run the live loop.")
    parser.add_argument("--live", action="store_true",
                        help="trade real money through ccxt (needs CTP_EXCHANGE, CTP_API_KEY, CTP_API_SECRET); "
                             "without it the loop paper-trades on live prices")
    args = parser.parse_args(argv)
    broker: Optional[Broker] = None
    if args.live:
        _load_dotenv()
        broker = CcxtBroker.from_env()  # exits naming any missing variable, before the trader is built
    base = os.path.dirname(__file__)
    config_path = os.path.join(base, "config", "config.yaml")
    trader = Trader(config_path, broker=broker)
    trader.cfg_loader.watch_and_reload()
    # Graceful slow-stop on SIGINT/SIGTERM
    import signal
    running = {"ok": True}

    def _sig_handler(_sig, _frm):
        try:
            os.makedirs("record", exist_ok=True)
            with open(os.path.join("record", "slow_stop.flag"), "w") as f:
                f.write("1\n")
        except Exception:
            pass
        running["ok"] = False

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    while True:
        try:
            trader.run_once()
        except Exception:
            pass
        if not running["ok"]:
            break
        try:
            loop_sec = float(trader.cfg_loader.get().raw.get("runtime", {}).get("loop_interval_seconds", 0))
        except Exception:
            loop_sec = 0.0
        if loop_sec > 0:
            time.sleep(loop_sec)


if __name__ == "__main__":
    main()
