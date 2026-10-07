import time
from typing import Dict, List, Optional

from bot.core.persistence import save_json
from bot.config.config_loader import ConfigLoader


def should_liquidate_by_age(opened_ts: float, maximum_holding_seconds: int) -> bool:
    return (time.time() - opened_ts) >= float(maximum_holding_seconds)


def persist_rotation(
    alloc_path: str,
    current_alloc: Dict[str, float],
    closed_symbol: str,
    freed_usd: float,
    dest_symbols: List[str],
    weights: Optional[List[float]] = None,
    cfg_loader: Optional[ConfigLoader] = None,
) -> Dict[str, float]:
    """Remove closed symbol from pack and add all freed USD to spare.

    - Sets allocation of `closed_symbol` to 0.0 so it won't be traded again.
    - Leaves other per-coin allocations unchanged.
    - Freed capital is implicitly added to spare (unallocated pool); no rotation.
    """
    alloc = dict(current_alloc or {})
    # Remove from coin packing so this symbol is no longer traded
    alloc[closed_symbol] = 0.0
    # Persist and return; freed_usd stays in spare implicitly
    save_json(alloc_path, alloc)
    return alloc

