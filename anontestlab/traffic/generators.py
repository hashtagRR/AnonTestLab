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


@dataclass
class ParetoTraffic(TrafficGenerator):
    """Bursty, heavy-tailed arrivals: inter-packet gaps ~ Pareto(shape),
    scaled to average 1/rate. Models self-similar traffic (long idle
    stretches punctuated by tight bursts), unlike Poisson's memoryless
    gaps. shape must be > 1 for a finite mean; smaller shape means a
    heavier tail (burstier)."""

    rate: float  # packets per second
    shape: float = 1.5

    def emission_times(self, rng: random.Random, duration: float) -> list[float]:
        if self.rate <= 0:
            return []
        mean_pareto = self.shape / (self.shape - 1)
        min_gap = (1.0 / self.rate) / mean_pareto
        times = []
        t = min_gap * rng.paretovariate(self.shape)
        while t < duration:
            times.append(t)
            t += min_gap * rng.paretovariate(self.shape)
        return times
