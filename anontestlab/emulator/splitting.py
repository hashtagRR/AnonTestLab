"""Split policies: which leg of a multipath session carries each cell.

- round_robin: legs in turn. With weights, a smooth weighted round-robin
  (each leg earns credit equal to its weight and the leg with the most
  credit sends), so the assignment stays deterministic and evenly spread.
- random: each cell to a uniformly chosen leg (the original behavior).
- iid: each cell to leg i with probability weights[i].
- batch: time is cut into batches with exponential durations (mean
  batch_mean_s); every cell in a batch goes to one leg, drawn with the
  weights. TrafficSliver-style splitting at a coarser granularity.
- latency: send on the lowest-RTT leg that has room in its window, where a
  leg's in-flight count is the number of cells sent on it within the last
  RTT. When every leg is full, the leg with the lowest in-flight share of
  its window sends. Modeled on the lowest-RTT-first idea of Tor's Conflux
  (Proposal 329); the RTTs are the configured nominal values and only drive
  the scheduling decision.
"""
from __future__ import annotations

import random
from collections import deque

POLICIES = ("round_robin", "random", "iid", "batch", "latency")


class LegScheduler:
    """Per-session state for one split policy."""

    def __init__(
        self,
        policy: str,
        num_legs: int,
        weights: list[float] | None = None,
        batch_mean_s: float = 2.0,
        leg_rtt_s: list[float] | None = None,
        leg_window: int = 8,
    ):
        if policy not in POLICIES:
            raise ValueError(f"unknown split policy {policy!r}, available: {list(POLICIES)}")
        self.policy = policy
        self.num_legs = num_legs
        total = sum(weights) if weights else float(num_legs)
        self.weights = [w / total for w in weights] if weights else [1.0 / num_legs] * num_legs
        self.batch_mean_s = batch_mean_s
        self.leg_rtt_s = leg_rtt_s or [0.05 * (i + 1) for i in range(num_legs)]
        self.leg_window = leg_window
        self._credit = [0.0] * num_legs
        self._rr_next = 0
        self._batch_end = -1.0
        self._batch_leg = 0
        self._recent: list[deque] = [deque() for _ in range(num_legs)]

    def assign(self, t: float, rng: random.Random) -> int:
        if self.num_legs == 1:
            return 0
        if self.policy == "round_robin":
            return self._round_robin()
        if self.policy == "random":
            return rng.randrange(self.num_legs)
        if self.policy == "iid":
            return self._draw(rng)
        if self.policy == "batch":
            if t >= self._batch_end:
                self._batch_leg = self._draw(rng)
                self._batch_end = t + rng.expovariate(1.0 / self.batch_mean_s)
            return self._batch_leg
        return self._lowest_rtt(t)

    def _draw(self, rng: random.Random) -> int:
        u = rng.random()
        acc = 0.0
        for leg, w in enumerate(self.weights):
            acc += w
            if u < acc:
                return leg
        return self.num_legs - 1

    def _round_robin(self) -> int:
        if len(set(self.weights)) == 1:
            leg = self._rr_next
            self._rr_next = (leg + 1) % self.num_legs
            return leg
        for leg in range(self.num_legs):
            self._credit[leg] += self.weights[leg]
        leg = max(range(self.num_legs), key=lambda i: self._credit[i])
        self._credit[leg] -= 1.0
        return leg

    def _lowest_rtt(self, t: float) -> int:
        for leg, sent in enumerate(self._recent):
            while sent and sent[0] <= t - self.leg_rtt_s[leg]:
                sent.popleft()
        by_rtt = sorted(range(self.num_legs), key=lambda i: self.leg_rtt_s[i])
        chosen = next((leg for leg in by_rtt if len(self._recent[leg]) < self.leg_window), None)
        if chosen is None:
            chosen = min(by_rtt, key=lambda i: len(self._recent[i]) / self.leg_window)
        self._recent[chosen].append(t)
        return chosen
