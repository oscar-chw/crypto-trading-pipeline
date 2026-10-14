"""Read-only consistency checks for saved offline replay audits; Python standard library only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Generator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

MAX_BYTES = 1024 * 1024
SCHEMA = "ctp-replay-audit/v1"


class AuditError(ValueError):
    """Invalid, unsupported or inconsistent saved audit."""


def fail(source: str, field: str, reason: str) -> NoReturn:
    raise AuditError(f"{source}: {field}: {reason}")


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate key {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite number {value}")


def decode(raw: bytes, source: str) -> dict[str, Any]:
    if len(raw) > MAX_BYTES:
        fail(source, "JSON", "inspection limit exceeds 1 MiB")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)
    except UnicodeDecodeError as error:
        raise AuditError(f"{source}: UTF-8: {error.reason}") from error
    except (ValueError, RecursionError) as error:
        raise AuditError(f"{source}: JSON: {error}") from error
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, float) and not math.isfinite(node):
            fail(source, "JSON", "number is not representable as finite binary64")
    return mapping(value, source, "record")


def mapping(value: Any, source: str, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(source, field, "object required")
    return value


def number(obj: dict, key: str, source: str) -> float:
    value = obj.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        fail(source, key, "finite number required; booleans are not numbers")
    try:
        result = float(value)
    except (ValueError, OverflowError) as error:
        raise AuditError(f"{source}: {key}: finite number required") from error
    if not math.isfinite(result):
        fail(source, key, "finite number required")
    return result


def integer(obj: dict, key: str, source: str) -> int:
    value = obj.get(key)
    if type(value) is not int or value < 0:
        fail(source, key, "nonnegative integer required")
    return value


def equal(actual: Any, expected: Any, source: str, field: str) -> None:
    if actual != expected:
        fail(source, field, f"expected {expected!r}; got {actual!r}")


def duration(value: Any, source: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9]+[mhd]", value.lower()):
        fail(source, "timeframe", "positive minute/hour/day duration required")
    try:
        count = int(value[:-1])
    except ValueError as error:
        raise AuditError(f"{source}: timeframe: duration exceeds the integer parsing limit") from error
    result = count * {"m": 60000, "h": 3600000, "d": 86400000}[value[-1].lower()]
    if result <= 0:
        fail(source, "timeframe", "positive duration required")
    return result


def records(path: Path, digest: Any) -> Generator[tuple[str, dict[str, Any]], None, None]:
    with path.open("rb") as stream:
        line = 0
        while raw := stream.readline(MAX_BYTES + 1):
            line += 1
            source = f"{path}:{line}"
            digest.update(raw)
            yield source, decode(raw, source)


@dataclass
class Account:
    declared: dict[str, Any]
    cash: float
    quantity: float = 0.0
    average: float = 0.0
    bars: int = 0
    buys: int = 0
    sells: int = 0
    fees: float = 0.0
    gaps: int = 0
    last_open: int | None = None
    liquidated: bool = False


def apply_event(account: Account, event: dict, source: str, span: int, fee_rate: float, slip: float) -> None:
    kind = event.get("type")
    index = integer(event, "bar_index", source)
    opened = integer(event, "bar_open_ts_ms", source)
    closed = integer(event, "bar_close_ts_ms", source)
    equal(closed, opened + span, source, "bar_close_ts_ms")
    if kind == "bar":
        if account.liquidated:
            fail(source, "bar_index", "bar follows final liquidation")
        equal(index, account.bars, source, "bar_index")
        if account.last_open is None:
            equal(opened, integer(account.declared, "first_bar_open_ts_ms", source), source, "bar_open_ts_ms")
        else:
            if opened <= account.last_open:
                fail(source, "bar_open_ts_ms", "timestamps must strictly increase")
            account.gaps += opened - account.last_open != span
        account.last_open = opened
        account.bars += 1
    elif kind == "liquidation":
        if account.liquidated or account.bars != integer(account.declared, "bars", source):
            fail(source, "liquidation", "one liquidation may follow the last declared bar")
        equal(index, account.bars - 1, source, "bar_index")
        equal(opened, account.last_open, source, "bar_open_ts_ms")
        equal(event.get("reason"), "end_of_data", source, "reason")
        account.liquidated = True
    else:
        fail(source, "type", "bar or liquidation required")

    mark = number(event, "mark_price", source)
    if mark <= 0:
        fail(source, "mark_price", "positive price required")
    equal(number(event, "cash_before", source), account.cash, source, "cash_before")
    equal(number(event, "quantity_before", source), account.quantity, source, "quantity_before")
    fills = event.get("fills")
    if not isinstance(fills, list):
        fail(source, "fills", "array required")
    for index, item in enumerate(fills):
        fill = mapping(item, source, f"fills[{index}]")
        side = fill.get("side")
        if side not in ("BUY", "SELL"):
            fail(source, "side", "BUY or SELL required")
        qty = number(fill, "qty", source)
        if qty <= 0:
            fail(source, "qty", "positive filled quantity required")
        price = number(fill, "price", source)
        equal(price, mark * (1 + slip if side == "BUY" else 1 - slip), source, "price")
        equal(integer(fill, "ts", source), opened, source, "ts")
        notional = price * qty
        fee = number(fill, "fee", source)
        equal(fee, fee_rate * notional, source, "fee")
        account.fees += fee
        if side == "BUY":
            if price * qty * (1 + fee_rate) > account.cash:
                # The broker's exact clip can itself round above the cash predicate.
                clipped = max(0.0, account.cash / (price * (1 + fee_rate) + 1e-12))
                if qty != clipped:
                    fail(source, "cash", "BUY exceeds available cash under the broker's clipped-fill rule")
            account.average = (account.average * account.quantity + notional) / (account.quantity + qty)
            account.quantity += qty
            account.cash -= notional + fee
            account.buys += 1
        else:
            if qty > account.quantity:
                fail(source, "qty", "sell exceeds held quantity")
            entry_notional = account.average * qty
            equal(number(fill, "pnl", source),
                  (notional - entry_notional) - (fee_rate * entry_notional + fee), source, "pnl")
            account.quantity -= qty
            if account.quantity <= 1e-12:  # existing BacktestBroker's declared residual-quantity clamp
                account.quantity, account.average = 0.0, 0.0
            account.cash += notional - fee
            account.sells += 1
    equal(number(event, "cash_after", source), account.cash, source, "cash_after")
    equal(number(event, "quantity_after", source), account.quantity, source, "quantity_after")
    equal(number(event, "equity_after", source), account.cash + account.quantity * mark, source, "equity_after")
    decision = event.get("decision")
    if decision not in ("warmup", "hold", "no_entry", "entry", "entry_blocked", "exit", "partial_take"):
        fail(source, "decision", "unknown decision")
    if kind == "bar":
        equal(decision == "warmup", event["bar_index"] < 30, source, "decision")
    statuses = mapping(event.get("signals"), source, "signals")
    if any(type(value) is not bool for value in statuses.values()):
        fail(source, "signals", "boolean signal statuses required")
    if event.get("entry_signal") is not None and type(event.get("entry_signal")) is not bool:
        fail(source, "entry_signal", "boolean or null required")


def inspect_run(directory: str | Path, expected_digest: str | None = None) -> dict:
    root = Path(directory)
    summary_path = root / "summary.json"
    with summary_path.open("rb") as stream:
        summary = decode(stream.read(MAX_BYTES + 1), f"{summary_path}:1")
    events_path = root / "events.jsonl"
    digest = hashlib.sha256()
    completed: dict | None = None
    with closing(records(events_path, digest)) as reader:
        try:
            source, header = next(reader)
        except StopIteration as error:
            raise AuditError(f"{events_path}:1: run: missing initial record") from error
        equal(header.get("type"), "run", source, "type")
        equal(header.get("schema"), SCHEMA, source, "schema")
        span = duration(header.get("timeframe"), source)
        assumptions = mapping(header.get("assumptions"), source, "assumptions")
        equal(assumptions.get("fill_model"), "same_bar_close_plus_directional_slippage", source, "fill_model")
        equal(assumptions.get("cash_model"), "independent_account_per_symbol", source, "cash_model")
        if assumptions.get("force_liquidation_at_end") is not True:
            fail(source, "force_liquidation_at_end", "boolean true required for the supported model")
        fee_rate = number(assumptions, "fee_rate_per_side", source)
        slip_bps = number(assumptions, "slippage_bps", source)
        cash = number(assumptions, "starting_cash_per_symbol", source)
        if not 0 <= fee_rate < 1 or not 0 <= slip_bps < 10000 or cash < 0:
            fail(source, "assumptions", "unsupported fee/slippage/cash range")
        inputs = mapping(header.get("inputs"), source, "inputs")
        if not inputs:
            fail(source, "inputs", "at least one symbol required")
        accounts = {symbol: Account(mapping(meta, source, "inputs"), cash) for symbol, meta in inputs.items()}
        for source, event in reader:
            if completed is not None:
                fail(source, "completed", "must be the final record")
            if event.get("type") == "completed":
                completed = event
            else:
                symbol = event.get("symbol")
                if not isinstance(symbol, str) or symbol not in accounts:
                    fail(source, "symbol", "not declared in run inputs")
                apply_event(accounts[symbol], event, source, span, fee_rate, slip_bps / 10000)
        if completed is None:
            fail(source, "completed", "missing final record")
        total_bars = sum(a.bars for a in accounts.values())
        equal(integer(completed, "symbols", source), len(accounts), source, "symbols")
        equal(integer(completed, "bars", source), total_bars, source, "bars")
        per_symbol = mapping(summary.get("per_symbol"), f"{summary_path}:1", "per_symbol")
        equal(completed.get("per_symbol"), per_symbol, f"{summary_path}:1", "completion/per_symbol")
        equal(set(per_symbol), set(accounts), f"{summary_path}:1", "symbols")
        aggregate = mapping(summary.get("aggregate"), f"{summary_path}:1", "aggregate")
        equal(integer(aggregate, "symbols", f"{summary_path}:1"), len(accounts), f"{summary_path}:1", "symbols")
        equal(integer(aggregate, "bars", f"{summary_path}:1"), total_bars, f"{summary_path}:1", "bars")
        for symbol, account in accounts.items():
            equal(account.bars, integer(account.declared, "bars", source), source, "bars")
            equal(account.last_open, integer(account.declared, "last_bar_open_ts_ms", source),
                  source, "last_bar_open_ts_ms")
            equal(account.gaps, integer(account.declared, "nonstandard_intervals", source),
                  source, "nonstandard_intervals")
            equal(account.quantity, 0.0, source, "quantity_after")
            metrics = mapping(per_symbol[symbol], f"{summary_path}:1", symbol)
            for field, expected in (("bars", account.bars), ("entries", account.buys), ("sells", account.sells)):
                equal(integer(metrics, field, f"{summary_path}:1"), expected, f"{summary_path}:1", field)
            equal(number(metrics, "pnl", f"{summary_path}:1"), account.cash - cash, f"{summary_path}:1", "pnl")
    actual_digest = digest.hexdigest()
    if expected_digest is not None and actual_digest != expected_digest.lower():
        fail(str(events_path), "SHA256", "does not match the supplied trusted digest")
    return {"status": "consistent", "schema": SCHEMA, "scope": "internal_accounting_consistency",
            "events_sha256": actual_digest, "digest_check": "matched" if expected_digest else "not_supplied",
            "assumptions": assumptions,
            "symbols": {symbol: {"bars": a.bars, "buys": a.buys, "sells": a.sells, "fees": a.fees,
                                 "cash_final": a.cash, "quantity_final": a.quantity}
                        for symbol, a in accounts.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect a saved offline replay audit without modifying it.")
    parser.add_argument("directory", help="directory containing events.jsonl and summary.json")
    parser.add_argument("--json", action="store_true", help="print the machine-readable consistency report")
    parser.add_argument("--expect-sha256", help="compare event bytes with a trusted 64-character SHA256")
    args = parser.parse_args(argv)
    if args.expect_sha256 is not None and not re.fullmatch(r"[a-fA-F0-9]{64}", args.expect_sha256):
        parser.error("--expect-sha256 needs a 64-character hexadecimal digest")
    try:
        report = inspect_run(args.directory, args.expect_sha256)
    except (AuditError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, sort_keys=True, allow_nan=False))
    else:
        print(f"Offline audit: {report['status']} ({SCHEMA})")
        for symbol, result in report["symbols"].items():
            print(f"  {symbol}: {result['bars']} bars, {result['buys']} buys, {result['sells']} sells; "
                  f"fees={result['fees']:.12g}, final cash={result['cash_final']:.12g}, "
                  f"quantity={result['quantity_final']:.12g}")
        print("Model: same-bar-close fills; independent account per symbol.")
        print(f"Events SHA256: {report['events_sha256']}; digest_check={report['digest_check']}")
        print("Scope: accounting consistency, not source authenticity or strategy validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
