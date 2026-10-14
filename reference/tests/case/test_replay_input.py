"""Imported candles fail before a replay can produce misleading results."""

import pytest
from backtest.runner import load_ohlcv_csv

pytestmark = pytest.mark.case
HEADER = "ts,open,high,low,close,volume\n"
VALID = "1735689600000,100,101,99,100,0\n"


@pytest.mark.parametrize("row,field", [
    ("1735689600000,100,101,99,nan,1\n", "close"),
    ("1735689600000,100,inf,99,100,1\n", "high"),
    ("1735689600000,0,101,0,100,1\n", "open"),
    ("1735689600000,100,101,99,100,-1\n", "volume"),
    ("1735689600000,100,90,99,100,1\n", "high"),
    ("1735689600000,100,101,102,100,1\n", "low"),
    ("-1,100,101,99,100,1\n", "ts"),
    ("1735689600000.5,100,101,99,100,1\n", "ts"),
    ("9999999999999999999999,100,101,99,100,1\n", "ts"),
    ("1735689600000,100,101,99,abc,1\n", "close"),
    ("1735689600000,100,101,99,,1\n", "close"),
])
def test_invalid_measure_names_path_line_and_field(tmp_path, row, field):
    path = tmp_path / "BTC_USDT.csv"
    path.write_text(HEADER + row)
    with pytest.raises(ValueError) as error:
        load_ohlcv_csv(str(path))
    message = str(error.value)
    assert str(path) in message and ":2:" in message and field in message


@pytest.mark.parametrize("content", [
    "ts,open,high,low,close\n1,100,101,99,100\n",
    "ts,open,high,low,close,close\n1,100,101,99,100,100\n",
    HEADER + VALID.rstrip() + ",extra\n",
    HEADER + "1,100,101,99,100\n",
])
def test_header_and_row_shape_refused(tmp_path, content):
    path = tmp_path / "bad.csv"
    path.write_text(content)
    with pytest.raises(ValueError, match=r"bad\.csv"):
        load_ohlcv_csv(str(path))


def test_zero_volume_and_gaps_are_preserved_not_repaired(tmp_path):
    path = tmp_path / "valid.csv"
    path.write_text(HEADER + VALID + "1735700400000,100,102,99,101,1\n")
    rows = load_ohlcv_csv(str(path))
    assert rows == [[1735689600000, 100, 101, 99, 100, 0], [1735700400000, 100, 102, 99, 101, 1]]
    path.write_text(HEADER + VALID + VALID)
    with pytest.raises(ValueError, match="strictly increasing"):
        load_ohlcv_csv(str(path))
