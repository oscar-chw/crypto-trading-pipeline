"""Saved audits can be checked without the trading stack or trusting their summary."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from backtest import runner

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def inspect_command(directory, *args):
    return subprocess.run([sys.executable, "-S", "-m", "backtest.inspect", str(directory), *args],
                          env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True, timeout=15)


@pytest.fixture(scope="module")
def original_bundle(tmp_path_factory):
    root = ROOT.parent
    directory = tmp_path_factory.mktemp("saved-audit") / "run"
    assert runner.main(["--config", str(root / "examples/paper-replay/config.yaml"),
                        "--data", str(root / "examples/paper-replay"), "--audit", str(directory)]) == 0
    return directory


@pytest.fixture
def bundle(original_bundle, tmp_path):
    target = tmp_path / "run"
    shutil.copytree(original_bundle, target)
    return target


def event_rows(bundle):
    return [json.loads(line) for line in (bundle / "events.jsonl").read_text().splitlines()]


def write_events(bundle, rows):
    (bundle / "events.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def test_saved_bundle_inspects_readonly_with_stdlib_only(bundle):
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    digest = hashlib.sha256(before["events.jsonl"]).hexdigest()
    run = inspect_command(bundle, "--json", "--expect-sha256", digest)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["status"] == "consistent" and report["digest_check"] == "matched"
    assert report["events_sha256"] == digest
    assert report["symbols"]["BTC/USDT"]["bars"] == 130
    assert report["symbols"]["BTC/USDT"]["buys"] == 2 and report["symbols"]["BTC/USDT"]["sells"] == 6
    assert report["assumptions"]["fee_rate_per_side"] == 0.001
    assert before == {p.name: p.read_bytes() for p in bundle.iterdir()}
    human = inspect_command(bundle)
    assert human.returncode == 0 and "130" in human.stdout and "BTC/USDT" in human.stdout
    assert "not_supplied" in human.stdout


@pytest.mark.parametrize("damage,field", [
    ("fee", "fee"), ("fill_price", "price"), ("cash", "cash_after"),
    ("quantity", "quantity_after"), ("equity", "equity_after"), ("index", "bar_index"),
    ("timestamp", "bar_close_ts_ms"), ("missing_bar", "bar_index"),
    ("missing_completion", "completed"), ("after_completion", "completed"),
    ("boolean_number", "mark_price"), ("nonfinite", "JSON"), ("unknown_symbol", "symbol"),
    ("unsupported_model", "fill_model"), ("gap_count", "nonstandard_intervals"),
    ("cash_before", "cash_before"), ("fill_pnl", "pnl"),
    ("range_end", "last_bar_open_ts_ms"), ("boolean_assumption", "force_liquidation_at_end"),
])
def test_inconsistent_records_fail_with_location(bundle, damage, field):
    rows = event_rows(bundle)
    fill = next(row for row in rows if row.get("fills"))
    bar = rows[1]
    if damage == "fee":
        fill["fills"][0]["fee"] += 0.01
    elif damage == "fill_price":
        fill["fills"][0]["price"] += 1
    elif damage in ("cash", "quantity", "equity"):
        fill[{"cash": "cash_after", "quantity": "quantity_after", "equity": "equity_after"}[damage]] += 1
    elif damage == "index":
        bar["bar_index"] = 4
    elif damage == "timestamp":
        bar["bar_close_ts_ms"] += 1
    elif damage == "missing_bar":
        rows.pop(1)
    elif damage == "missing_completion":
        rows.pop()
    elif damage == "after_completion":
        rows.append(dict(rows[-1]))
    elif damage == "boolean_number":
        bar["mark_price"] = True
    elif damage == "nonfinite":
        bar["mark_price"] = float("nan")
    elif damage == "unknown_symbol":
        bar["symbol"] = "UNKNOWN/USDT"
    elif damage == "unsupported_model":
        rows[0]["assumptions"]["fill_model"] = "invented"
    elif damage == "cash_before":
        fill["cash_before"] += 1
    elif damage == "fill_pnl":
        sell = next(e for e in rows if e.get("fills") and e["fills"][0]["side"] == "SELL")
        sell["fills"][0]["pnl"] += 1
    elif damage == "range_end":
        rows[0]["inputs"]["BTC/USDT"]["last_bar_open_ts_ms"] += 1
    elif damage == "boolean_assumption":
        rows[0]["assumptions"]["force_liquidation_at_end"] = 1
    else:
        rows[0]["inputs"]["BTC/USDT"]["nonstandard_intervals"] += 1
    write_events(bundle, rows)
    run = inspect_command(bundle, "--json")
    assert run.returncode == 2
    assert "events.jsonl:" in run.stderr and field in run.stderr, run.stderr
    assert not run.stdout


@pytest.mark.parametrize("damage", ["aggregate", "completion_mismatch"])
def test_summary_mismatch_is_not_accepted(bundle, damage):
    path = bundle / "summary.json"
    summary = json.loads(path.read_text())
    if damage == "aggregate":
        summary["aggregate"]["bars"] += 1
    else:
        summary["per_symbol"]["BTC/USDT"]["entries"] += 1
    path.write_text(json.dumps(summary))
    run = inspect_command(bundle)
    assert run.returncode == 2 and "summary.json" in run.stderr


@pytest.mark.parametrize("field", ["entries", "pnl"])
def test_summary_and_completion_cannot_jointly_forge_account_result(bundle, field):
    rows = event_rows(bundle)
    rows[-1]["per_symbol"]["BTC/USDT"][field] += 1
    write_events(bundle, rows)
    path = bundle / "summary.json"
    summary = json.loads(path.read_text())
    summary["per_symbol"] = rows[-1]["per_symbol"]
    path.write_text(json.dumps(summary))
    result = inspect_command(bundle)
    assert result.returncode == 2 and field in result.stderr


@pytest.mark.parametrize("content,needle", [
    (b'{"type":"run","type":"run"}\n', "duplicate"),
    (b'{"type":', "JSON"), (b'\xff\n', "UTF-8"),
    (b' ' * (1024 * 1024 + 1) + b'\n', "limit"),
], ids=["duplicate-key", "truncated-json", "invalid-utf8", "oversized-line"])
def test_malformed_or_oversized_records_are_refused(bundle, content, needle):
    (bundle / "events.jsonl").write_bytes(content)
    run = inspect_command(bundle)
    assert run.returncode == 2 and "events.jsonl:1:" in run.stderr and needle in run.stderr


def test_missing_files_digest_mismatch_and_recovery(bundle):
    events = bundle / "events.jsonl"
    original = events.read_bytes()
    run = inspect_command(bundle, "--expect-sha256", "0" * 64)
    assert run.returncode == 2 and "SHA256" in run.stderr
    events.unlink()
    run = inspect_command(bundle)
    assert run.returncode == 2 and "events.jsonl" in run.stderr
    events.write_bytes(original)
    run = inspect_command(bundle, "--json")
    assert run.returncode == 0 and json.loads(run.stdout)["status"] == "consistent"


def test_duplicate_key_is_rejected_in_an_otherwise_valid_bundle(bundle):
    path = bundle / "events.jsonl"
    lines = path.read_text().splitlines()
    lines[0] = lines[0][:-1] + ',"type":"run"}'
    path.write_text("\n".join(lines) + "\n")
    run = inspect_command(bundle)
    assert run.returncode == 2 and "duplicate" in run.stderr


def test_valid_json_over_record_limit_is_refused_before_parsing(bundle):
    rows = event_rows(bundle)
    rows[0]["padding"] = "x" * (1024 * 1024)
    write_events(bundle, rows)
    run = inspect_command(bundle)
    assert run.returncode == 2 and "limit" in run.stderr


def test_timeframe_integer_conversion_limit_has_a_field_diagnostic(bundle):
    rows = event_rows(bundle)
    rows[0]["timeframe"] = "9" * 5000 + "m"
    write_events(bundle, rows)
    run = inspect_command(bundle)
    assert run.returncode == 2
    assert "events.jsonl:1:" in run.stderr and "timeframe" in run.stderr
    assert "Traceback" not in run.stderr and not run.stdout
