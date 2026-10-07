import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict

import yaml


@dataclass
class AppConfig:
    raw: Dict[str, Any]

    @property
    def detail_console_output(self) -> bool:
        return bool(self.raw.get("detail_console_output", False))

    @property
    def initial_capital(self) -> float:
        return float(self.raw.get("initial_capital", 0.0))

    @property
    def transaction_fee(self) -> float:
        return float(self.raw.get("transaction_fee", 0.0))

    @property
    def crypto_list(self) -> Dict[str, bool]:
        return dict(self.raw.get("crypto_list", {}))

    @property
    def portfolio(self) -> Dict[str, Any]:
        return dict(self.raw.get("portfolio", {}))

    @property
    def stop_loss_take_gain(self) -> Dict[str, Any]:
        return dict(self.raw.get("stop_loss_take_gain", {}))

    @property
    def rate_limit(self) -> Dict[str, Any]:
        return dict(self.raw.get("rate_limit", {}))

    @property
    def signal_portfolio(self) -> Dict[str, Any]:
        return dict(self.raw.get("signal_portfolio", {}))


class ConfigLoader:
    def __init__(self, config_path: str) -> None:
        self._path = config_path
        self._lock = threading.RLock()
        self._config = self._load()
        self._last_mtime = os.path.getmtime(self._path)

    def _load(self) -> AppConfig:
        with open(self._path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return AppConfig(raw=data)

    def get(self) -> AppConfig:
        with self._lock:
            return self._config

    def reload_if_changed(self) -> bool:
        try:
            mtime = os.path.getmtime(self._path)
        except FileNotFoundError:
            return False
        if mtime != self._last_mtime:
            with self._lock:
                self._config = self._load()
                self._last_mtime = mtime
            return True
        return False

    def watch_and_reload(self, interval_seconds: float = 2.0) -> None:
        def _loop() -> None:
            while True:
                try:
                    self.reload_if_changed()
                except Exception:
                    pass
                time.sleep(interval_seconds)

        t = threading.Thread(target=_loop, name="ConfigWatcher", daemon=True)
        t.start()


