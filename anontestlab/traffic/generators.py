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


@dataclass
class BurstTraffic(TrafficGenerator):
    """Bursts of back-to-back cells, the shape of web and bulk transfers over
    Tor. Bursts start as a Poisson process of rate rate / burst_mean_cells;
    each carries a geometric number of cells (mean burst_mean_cells, at least
    one) sent burst_gap_ms apart, so the long-run cell rate is `rate`. For
    bins much longer than a burst, the per-bin counts have index of
    dispersion 2 * burst_mean_cells - 1 (1 for Poisson)."""

    rate: float  # cells per second
    burst_mean_cells: float = 12.0
    burst_gap_ms: float = 2.0

    def emission_times(self, rng: random.Random, duration: float) -> list[float]:
        if self.rate <= 0:
            return []
        mean = max(self.burst_mean_cells, 1.0)
        burst_rate = self.rate / mean
        gap = self.burst_gap_ms / 1000.0
        stop = 1.0 / mean  # geometric on 1, 2, ... with this mean
        times = []
        t = rng.expovariate(burst_rate)
        while t < duration:
            cell_t = t
            while cell_t < duration:
                times.append(cell_t)
                if rng.random() < stop:
                    break
                cell_t += gap
            t += rng.expovariate(burst_rate)
        times.sort()
        return times
