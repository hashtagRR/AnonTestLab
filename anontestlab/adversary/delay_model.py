"""Samples the added delay a packet picks up between the entry observation
point and the exit observation point, from an experiment's own mixing and
link settings. Attackers that assume knowledge of the defense (the
likelihood-ratio attacker and the timing-window matcher) use these samples
as the delay distribution, and the lag-aware correlator uses them to set its
lag range.

The model covers the relay-side mixing in emulator/mixing.py and the
per-hop link latency. It ignores host scheduling noise, which the fidelity
check measures separately.
"""
from __future__ import annotations

import numpy as np


def sample_added_delay(config, n: int, rng: np.random.Generator) -> np.ndarray:
    """n draws of the total added delay in seconds over path 0's hops."""
    hops = config.path_length
    total = np.zeros(n)
    for _ in range(hops):
        total += _mixing_delay(config, n, rng)
        latency = config.link_latency_ms / 1000.0
        jitter = config.link_jitter_ms / 1000.0
        if latency > 0 or jitter > 0:
            total += np.maximum(0.0, rng.normal(latency, jitter, n))
    return total


def _mixing_delay(config, n: int, rng: np.random.Generator) -> np.ndarray:
    strategy = config.mix_strategy
    if strategy == "none":
        return np.zeros(n)
    if strategy == "constant":
        return np.full(n, config.mix_delay_ms / 1000.0)
    if strategy == "exponential":
        return rng.exponential(config.mix_delay_ms / 1000.0, n)
    if strategy == "pool":
        interval = config.pool_interval_ms / 1000.0
        jitter = config.pool_interval_jitter
        # wait for the next flush (arrival uniform within the current interval),
        # then a geometric number of further flushes while the cell is retained
        first = rng.uniform(0.0, 1.0, n) * interval * (1 + rng.uniform(-jitter, jitter, n))
        extra_rounds = rng.geometric(config.pool_release_probability, n) - 1
        return first + extra_rounds * interval
    raise ValueError(f"no delay model for mixing strategy {strategy!r}")


def delay_quantiles(config, qs: tuple[float, ...], n: int = 200_000, seed: int = 0) -> dict[float, float]:
    samples = sample_added_delay(config, n, np.random.default_rng(seed))
    return {q: float(np.quantile(samples, q)) for q in qs}


def delay_density(config, step_s: float, n: int = 400_000, seed: int = 0) -> np.ndarray:
    """Histogram estimate of the added-delay density on a grid of width
    step_s starting at 0, in units of 1/second. The last bin reaches the
    99.99th percentile."""
    samples = sample_added_delay(config, n, np.random.default_rng(seed))
    top = float(np.quantile(samples, 0.9999)) + step_s
    n_bins = max(1, int(np.ceil(top / step_s)))
    hist, _ = np.histogram(samples, bins=n_bins, range=(0.0, n_bins * step_s))
    return hist / (n * step_s)
