"""Point-in-time store: append-only records, read through a view pinned to `as_of`.

A record has an event time (what it describes) and `available_at` (when we could first know it). A view
returns only records with available_at <= as_of, and refuses any read whose window ends after as_of.
A correction is appended as a new record for the same event time with a later available_at; it replaces
the old value only for views whose as_of is at or after the correction's publication.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Any

from pipeline.types import Bar, UtcNanos


class LookAheadError(RuntimeError):
    """A read asked for data later than the view's as_of."""


@dataclass(frozen=True)
class Record:
    key: str
    event_time: UtcNanos
    available_at: UtcNanos
    value: Any


class PointInTimeStore:
    def __init__(self) -> None:
        self._rows: dict[str, list[Record]] = {}
        self._seen: set[tuple[str, UtcNanos, UtcNanos]] = set()

    def append(self, key: str, event_time: UtcNanos, available_at: UtcNanos, value: Any) -> Record:
        if available_at < event_time:
            raise ValueError("available_at must be >= event_time")
        ident = (key, int(event_time), int(available_at))
        if ident in self._seen:
            raise ValueError(f"duplicate record {ident}: the store is append-only")
        rec = Record(key, int(event_time), int(available_at), value)
        rows = self._rows.setdefault(key, [])
        bisect.insort(rows, rec, key=lambda r: (r.event_time, r.available_at))
        self._seen.add(ident)
        return rec

    def append_bar(self, bar: Bar) -> Record:
        return self.append(bar.instrument_id, bar.close_time, bar.available_at, bar)

    def view(self, as_of: UtcNanos) -> "PointInTimeView":
        return PointInTimeView(self._rows, int(as_of))


class PointInTimeView:
    def __init__(self, rows: dict[str, list[Record]], as_of: UtcNanos) -> None:
        self._rows = rows
        self.as_of = as_of

    def read(self, key: str, start: UtcNanos, end: UtcNanos) -> list[Record]:
        """Records with start < event_time <= end, latest revision known at as_of, sorted by event time."""
        if end > self.as_of:
            raise LookAheadError(f"read up to {end} from a view as of {self.as_of}")
        latest: dict[UtcNanos, Record] = {}
        for r in self._rows.get(key, []):
            if start < r.event_time <= end and r.available_at <= self.as_of:
                latest[r.event_time] = r  # rows are sorted by available_at within an event time
        return [latest[k] for k in sorted(latest)]

    def latest(self, key: str) -> Record | None:
        rows = self.read(key, -(2**62), self.as_of)
        return rows[-1] if rows else None
