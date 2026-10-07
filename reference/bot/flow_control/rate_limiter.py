import time
from collections import deque
from typing import Deque


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self.max_per_minute = max_per_minute
        self._events: Deque[float] = deque()

    def allow(self) -> bool:
        now = time.time()
        window_start = now - 60.0
        while self._events and self._events[0] < window_start:
            self._events.popleft()
        if len(self._events) < self.max_per_minute:
            self._events.append(now)
            return True
        return False


