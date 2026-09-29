"""Relay-side mixing: when a relay actually transmits a DATA cell it has
decided to forward. One Mixer per relay process, shared by every circuit
through that relay, so a pool mixes cells from different sessions.

Strategies:

- none: transmit immediately and inline, exactly the pre-mixing behavior
  (a circuit's cells stay in order and queue behind each other's link
  delays).
- constant: every cell waits the same delay_s. Shifts timing without
  reordering; included as the sanity case that a lag-aware observer should
  fully undo.
- exponential: every cell waits an independent Exponential(mean=delay_s)
  delay (Loopix/Nym-style continuous-time mixing). Cells can overtake each
  other.
- pool: cells accumulate in one relay-wide pool that is flushed every
  interval_s (optionally jittered by +/- interval_jitter, a fraction of
  interval_s, for randomized flushing). At each flush every pooled cell is
  independently released with release_probability. 1.0 is a timed pool
  that empties completely (burst release, the ASN-style batch); < 1 is a
  binomial/retained pool where a cell can survive several flushes
  (geometric sojourn). Released cells go out in shuffled order.
"""
from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Awaitable, Callable

STRATEGIES = ("none", "constant", "exponential", "pool")

Send = Callable[[], Awaitable[None]]


class Mixer:
    def __init__(
        self,
        strategy: str = "none",
        delay_s: float = 0.0,
        interval_s: float = 0.1,
        release_probability: float = 1.0,
        interval_jitter: float = 0.0,
        rng: random.Random | None = None,
    ):
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown mixing strategy {strategy!r}, available: {list(STRATEGIES)}")
        self.strategy = strategy
        self.delay_s = delay_s
        self.interval_s = interval_s
        self.release_probability = release_probability
        self.interval_jitter = interval_jitter
        self.rng = rng if rng is not None else random.Random()
        self._pool: list[Send] = []
        self._flusher: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()  # strong refs so pending sends aren't garbage-collected

    @property
    def pool_size(self) -> int:
        return len(self._pool)

    async def submit(self, send: Send) -> None:
        """Hand over one transmission. Returns once the cell is queued (or,
        for strategy none, once it has been sent)."""
        if self.strategy == "none":
            await send()
        elif self.strategy == "constant":
            self._spawn(self._delayed(self.delay_s, send))
        elif self.strategy == "exponential":
            self._spawn(self._delayed(self.rng.expovariate(1.0 / self.delay_s), send))
        else:
            self._pool.append(send)
            if self._flusher is None:
                self._flusher = asyncio.create_task(self._flush_loop())

    def flush(self) -> int:
        """Release this round's cells from the pool; returns how many."""
        pool = self._pool
        self.rng.shuffle(pool)
        if self.release_probability >= 1.0:
            released, kept = pool, []
        else:
            released, kept = [], []
            for send in pool:
                (released if self.rng.random() < self.release_probability else kept).append(send)
        self._pool = kept
        for send in released:
            self._spawn(_guarded(send))
        return len(released)

    async def _flush_loop(self) -> None:
        while True:
            interval = self.interval_s
            if self.interval_jitter > 0:
                interval *= 1 + self.rng.uniform(-self.interval_jitter, self.interval_jitter)
            await asyncio.sleep(interval)
            self.flush()

    async def _delayed(self, delay: float, send: Send) -> None:
        await asyncio.sleep(delay)
        await _guarded(send)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def _guarded(send: Send) -> None:
    # A deferred send can outlive its circuit (the session ended or the
    # downstream connection closed while the cell sat in the mix). That
    # cell is simply lost, like one still inside a real mix at shutdown.
    with contextlib.suppress(ConnectionError, OSError):
        await send()
