import pytest


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """Run in an empty directory with no exchange credentials; the code writes record/ and log/ here."""
    for name in ("CTP_EXCHANGE", "CTP_API_KEY", "CTP_API_SECRET", "EXCHANGE_API_KEY", "EXCHANGE_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path
