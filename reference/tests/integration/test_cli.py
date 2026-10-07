"""The command-line entry points, run as subprocesses."""
import json
import os
import subprocess
import sys

import pytest
from tests.fakes import REPO

pytestmark = pytest.mark.integration


def _run(args, cwd, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CTP_", "EXCHANGE_API"))}
    env.update(PYTHONPATH=REPO, PYTHONDONTWRITEBYTECODE="1", **(env_extra or {}))
    return subprocess.run([sys.executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)


def test_live_entry_point_exits_clearly_without_credentials(tmp_path):
    r = _run(["-m", "bot.trader", "--live"], cwd=tmp_path)
    assert r.returncode != 0
    assert "CTP_EXCHANGE, CTP_API_KEY, CTP_API_SECRET" in r.stderr
    # refused before the trader was built: no log file, no trade records
    assert not (tmp_path / "log").exists() and not (tmp_path / "record").exists()


def test_offline_backtest_is_deterministic(tmp_path):
    r = _run(["-m", "backtest.synthetic", str(tmp_path / "data"), "--bars", "300"], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    outs = []
    for n in (1, 2):
        r = _run(["-m", "backtest.runner", "--data", str(tmp_path / "data"), "--out", str(tmp_path / f"out{n}.json")], cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        s = json.loads((tmp_path / f"out{n}.json").read_text())
        assert s["aggregate"]["bars"] == 4 * 300
        s["aggregate"].pop("seconds"), s["aggregate"].pop("bars_per_second")
        outs.append(s)
    assert outs[0] == outs[1]


def test_backtest_refuses_an_empty_data_directory(tmp_path):
    (tmp_path / "empty").mkdir()
    r = _run(["-m", "backtest.runner", "--data", str(tmp_path / "empty")], cwd=tmp_path)
    assert r.returncode == 2 and "no candles" in r.stderr
