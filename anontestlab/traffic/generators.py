from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass


class TrafficGenerator(ABC):
    """Produces packet-emission timestamps for one session over a window."""

    @abstractmethod
    def emission_times(self, rng: random.Random, duration: float) -> list[float]:
        ...


@dataclass
class PoissonTraffic(TrafficGenerator):
    """Memoryless arrivals: inter-packet gaps ~ Exponential(rate)."""

    rate: float  # packets per second

    def emission_times(self, rng: random.Random, duration: float) -> list[float]:
        if self.rate <= 0:
            return []
        times = []
        t = rng.expovariate(self.rate)
        while t < duration:
            times.append(t)
            t += rng.expovariate(self.rate)
        return times


@dataclass
class ConstantRateTraffic(TrafficGenerator):
    """Fixed inter-packet gap of 1/rate."""

    rate: float  # packets per second

    def emission_times(self, rng: random.Random, duration: float) -> list[float]:
        if self.rate <= 0:
            return []
        gap = 1.0 / self.rate
        times = []
        t = gap
        while t < duration:
            times.append(t)
            t += gap
        return times
