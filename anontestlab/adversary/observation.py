"""Turns raw packet timestamps into a fixed-width time series an
adversary can compare across sessions."""
from __future__ import annotations

import numpy as np


def bin_counts(times: list[float], bin_size: float, n_bins: int) -> np.ndarray:
    counts = np.zeros(n_bins)
    for t in times:
        b = int(t // bin_size)
        if 0 <= b < n_bins:
            counts[b] += 1
    return counts
