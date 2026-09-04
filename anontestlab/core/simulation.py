"""Minimal discrete-event simulation engine.

A dependency-free heap-based event loop. Callbacks are scheduled at a
future simulation time and run in timestamp order; ties are broken by
insertion order so scheduling stays deterministic under a fixed seed.
"""
from __future__ import annotations

import heapq
import itertools
from typing import Callable


class Simulation:
    def __init__(self) -> None:
        self.now: float = 0.0
        self._queue: list[tuple[float, int, Callable[[], None]]] = []
        self._counter = itertools.count()

    def schedule(self, delay: float, callback: Callable[[], None]) -> None:
        if delay < 0:
            raise ValueError(f"delay must be non-negative, got {delay}")
        heapq.heappush(self._queue, (self.now + delay, next(self._counter), callback))

    def run(self, until: float | None = None) -> None:
        while self._queue:
            event_time, _, callback = self._queue[0]
            if until is not None and event_time > until:
                break
            heapq.heappop(self._queue)
            self.now = event_time
            callback()
        if until is not None:
            self.now = until
