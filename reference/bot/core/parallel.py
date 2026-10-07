from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Iterable, List, Tuple


def parallel_map(func: Callable[[Any], Any], items: Iterable[Any], max_workers: int = 8) -> List[Any]:
    futures = []
    results: List[Any] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for item in items:
            futures.append(pool.submit(func, item))
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception:
                results.append(None)
    return results


def parallel_dict(func: Callable[[Any], Tuple[Any, Any]], items: Iterable[Any], max_workers: int = 8) -> Dict[Any, Any]:
    futures = []
    out: Dict[Any, Any] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for item in items:
            futures.append(pool.submit(func, item))
        for fut in as_completed(futures):
            try:
                k, v = fut.result()
                out[k] = v
            except Exception:
                pass
    return out


