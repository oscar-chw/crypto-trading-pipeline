import logging
import time
from pathlib import Path


def setup_file_logger(name: str = "trading_bot") -> logging.Logger:
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{name}_{ts}.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.info("Logger initialized -> %s", str(log_path))
    return logger


