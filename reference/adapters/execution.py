"""Stage 07 ExecutionVenue over PaperBroker (bot/api/exchange.py), the live loop's default broker.

PaperBroker prices fills with the backtester's model (backtest/runner.py BacktestBroker), so this venue,
paper trading and the backtest all charge the same costs. CcxtBroker is not wrapped: every call is a live order.
"""
from bot.api.exchange import PaperBroker
from pipeline.types import Fill, OrderIntent


class BrokerVenue:
    """Prices one market order with PaperBroker at `mid`: mid +/- slippage_bps, fee_rate per side.

    The broker is spot and long-only and tracks cash and inventory; the Protocol prices a single fill, so each
    order goes to a fresh paper account holding exactly the cash or quantity it needs. bar_volume is unused:
    the bot has no market-impact model.
    """

    def __init__(self, fee_rate: float, slippage_bps: float) -> None:
        self.fee_rate, self.slippage_bps = fee_rate, slippage_bps

    def submit(self, order: OrderIntent, mid: float, bar_volume: float) -> Fill:
        qty = abs(order.qty)
        symbol = order.instrument_id
        cash, holdings = 0.0, {symbol: (qty, mid)}
        if order.qty > 0:
            cash = 2.0 * mid * qty * (1.0 + self.slippage_bps / 10_000.0) * (1.0 + self.fee_rate)
            holdings = {}
        paper = PaperBroker(lambda _symbol: mid, self.fee_rate, self.slippage_bps, cash=cash, holdings=holdings)
        fill = paper.place_market_order(symbol, "BUY" if order.qty > 0 else "SELL", qty)
        signed = fill.filled if order.qty > 0 else -fill.filled
        return Fill(order.client_id, order.instrument_id, order.t, signed, fill.price, fill.fee)
