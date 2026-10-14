"""The useful offline path has inspectable, reproducible artifacts and honest failure status."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from backtest import runner
from backtest.synthetic import make_candles, write_csv
from tests.fakes import CONFIG

pytestmark = pytest.mark.integration


def inputs(tmp_path):
    cfg = yaml.safe_load(Path(CONFIG).read_text())
    cfg["crypto_list"] = {"BTC/USDT": True}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(cfg))
    data = tmp_path / "data"
    data.mkdir()
    csv = data / "BTC_USDT.csv"
    write_csv(str(csv), make_candles(130, 7))
    return config, data, csv


def command(config, data, output):
    return ["--config", str(config), "--data", str(data), "--audit", str(output)]


def test_cli_audit_has_assumptions_inputs_decisions_and_actual_fills(tmp_path):
    config, data, csv = inputs(tmp_path)
    before = csv.read_bytes()
    first, second = tmp_path / "run1", tmp_path / "run2"
    assert runner.main(command(config, data, first)) == 0
    assert runner.main(command(config, data, second)) == 0
    assert (first / "events.jsonl").read_bytes() == (second / "events.jsonl").read_bytes()
    assert csv.read_bytes() == before
    events = [json.loads(line) for line in (first / "events.jsonl").read_text().splitlines()]
    meta = events[0]
    assert meta["type"] == "run" and meta["schema"] == "ctp-replay-audit/v1"
    assert meta["assumptions"]["fill_model"] == "same_bar_close_plus_directional_slippage"
    assert meta["assumptions"]["cash_model"] == "independent_account_per_symbol"
    assert meta["assumptions"]["fee_rate_per_side"] == 0.0001
    assert meta["assumptions"]["slippage_bps"] == 1.0
    normalized = json.dumps(runner.load_ohlcv_csv(str(csv)), separators=(",", ":"), allow_nan=False).encode()
    assert meta["inputs"]["BTC/USDT"]["parsed_candles_sha256"] == hashlib.sha256(normalized).hexdigest()
    bars = [e for e in events if e["type"] == "bar"]
    assert len(bars) == 130 and [e["bar_index"] for e in bars] == list(range(130))
    assert all(e["decision"] == "warmup" for e in bars[:30])
    assert all(e["bar_close_ts_ms"] == e["bar_open_ts_ms"] + 3_600_000 for e in bars)
    fills = [f for e in events[1:-1] for f in e["fills"]]
    assert any(f["side"] == "BUY" for f in fills) and any(f["side"] == "SELL" for f in fills)
    for event in events[1:-1]:
        cash, qty = event["cash_before"], event["quantity_before"]
        for fill in event["fills"]:
            sign = 1 if fill["side"] == "BUY" else -1
            assert fill["price"] == pytest.approx(event["mark_price"] * (1 + sign / 10000))
            assert fill["fee"] == pytest.approx(fill["price"] * fill["qty"] * 0.0001)
            cash -= sign * fill["price"] * fill["qty"] + fill["fee"]
            qty += sign * fill["qty"]
        assert event["cash_after"] == pytest.approx(cash)
        assert event["quantity_after"] == pytest.approx(qty, abs=1e-10)
    summary = json.loads((first / "summary.json").read_text())
    assert events[-1]["type"] == "completed" and events[-1]["per_symbol"] == summary["per_symbol"]
    assert not list(tmp_path.glob(".ctp-replay-*"))


def test_bad_input_has_no_success_artifact_and_correction_recovers(tmp_path, capsys):
    config, data, csv = inputs(tmp_path)
    original = csv.read_text()
    csv.write_text(original.replace(",", ",nan,", 1))  # invalid header
    output = tmp_path / "run"
    assert runner.main(command(config, data, output)) == 2
    assert "BTC_USDT.csv" in capsys.readouterr().err and not output.exists()
    csv.write_text(original)
    assert runner.main(command(config, data, output)) == 0
    assert (output / "summary.json").is_file()
    before = (output / "events.jsonl").read_bytes()
    assert runner.main(command(config, data, output)) == 2
    assert (output / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_interrupted_audit_does_not_publish_a_partial_run(tmp_path, monkeypatch, failure):
    config, data, _ = inputs(tmp_path)
    output = tmp_path / "run"

    def interrupted(*args, on_event=None, **kwargs):
        on_event({"type": "partial_test_event"})
        raise failure("injected replay failure")

    monkeypatch.setattr(runner, "run_backtest", interrupted)
    if failure is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            runner.main(command(config, data, output))
    else:
        assert runner.main(command(config, data, output)) == 2
    assert not output.exists() and not list(tmp_path.glob(".ctp-replay-*"))


def test_summary_output_cannot_overwrite_input(tmp_path, capsys):
    config, data, csv = inputs(tmp_path)
    original = csv.read_bytes()
    assert runner.main(["--config", str(config), "--data", str(data), "--out", str(csv)]) == 2
    assert "input" in capsys.readouterr().err.lower()
    assert csv.read_bytes() == original


@pytest.mark.parametrize("field,value", [("transaction_fee", -0.01), ("transaction_fee", float("nan")),
                                        ("slippage_bps", -1), ("slippage_bps", 10000),
                                        ("initial_capital_in_usd", -1)])
def test_invalid_cost_or_cash_settings_fail_before_output(tmp_path, capsys, field, value):
    config, data, _ = inputs(tmp_path)
    cfg = yaml.safe_load(config.read_text())
    target = cfg["portfolio"] if field == "slippage_bps" else cfg
    target[field] = value
    config.write_text(yaml.safe_dump(cfg))
    output = tmp_path / "bad-run"
    assert runner.main(command(config, data, output)) == 2
    assert field in capsys.readouterr().err and not output.exists()


def test_missing_enabled_symbol_is_reported_in_manifest_and_warning(tmp_path, capsys):
    config, data, _ = inputs(tmp_path)
    cfg = yaml.safe_load(config.read_text())
    cfg["crypto_list"]["ETH/USDT"] = True
    config.write_text(yaml.safe_dump(cfg))
    output = tmp_path / "partial-universe"
    assert runner.main(command(config, data, output)) == 0
    meta = json.loads((output / "events.jsonl").read_text().splitlines()[0])
    assert meta["missing_symbols"] == ["ETH/USDT"]
    assert "ETH/USDT" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
def test_input_alias_cannot_be_used_as_summary_output(tmp_path, kind):
    config, data, csv = inputs(tmp_path)
    alias = tmp_path / "alias.json"
    if kind == "hardlink":
        alias.hardlink_to(csv)
    else:
        alias.symlink_to(csv)
    original = csv.read_bytes()
    assert runner.main(["--config", str(config), "--data", str(data), "--out", str(alias)]) == 2
    assert csv.read_bytes() == original


@pytest.mark.parametrize("stage", ["write", "flush"])
@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_stdout_failure_aborts_before_audit_publication_and_can_recover(tmp_path, monkeypatch, stage, failure):
    config, data, _ = inputs(tmp_path)
    output = tmp_path / "run"

    class FailingStdout:
        def write(self, text):
            if stage == "write":
                raise failure("injected stdout write failure")
            return len(text)

        def flush(self):
            if stage == "flush":
                raise failure("injected stdout flush failure")

    with monkeypatch.context() as patch:
        patch.setattr(runner.sys, "stdout", FailingStdout())
        if failure is KeyboardInterrupt:
            with pytest.raises(KeyboardInterrupt):
                runner.main(command(config, data, output))
        else:
            assert runner.main(command(config, data, output)) == 2
    assert not output.exists() and not list(tmp_path.glob(".ctp-replay-*"))
    assert runner.main(command(config, data, output)) == 0
    assert (output / "events.jsonl").is_file() and (output / "summary.json").is_file()


def test_closed_stdout_pipe_has_clean_cli_failure_and_same_destination_recovers(tmp_path):
    config, data, _ = inputs(tmp_path)
    output = tmp_path / "run"
    argv = [sys.executable, "-m", "backtest.runner", *command(config, data, output)]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        result = subprocess.run(argv, env=env, stdout=write_fd, stderr=subprocess.PIPE, text=True, timeout=30)
    finally:
        os.close(write_fd)
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr and "Exception ignored" not in result.stderr
    assert not output.exists() and not list(tmp_path.glob(".ctp-replay-*"))
    recovered = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30)
    assert recovered.returncode == 0, recovered.stderr
    assert (output / "events.jsonl").is_file() and (output / "summary.json").is_file()
