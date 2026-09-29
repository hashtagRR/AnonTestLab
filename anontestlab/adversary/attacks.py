"""Score functions for the training-free correlation attackers. Each takes
the per-session ingress (entry-side) and egress (exit-side) timestamp lists
and returns an n x n score matrix: row i is ingress session i, column j is
egress session j, and the diagonal holds the true pairs.

- lag_correlation_scores: binned-count Pearson correlation, maximised over
  non-negative lags (A1). With max_lag_bins=0 it is the zero-lag correlator
  (A0).
- likelihood_ratio_scores: point-process log-likelihood ratio of the egress
  times given the ingress times and a known delay density (A2), after
  Danezis, "The Traffic Analysis of Continuous-Time Mixes", PET 2004.
- window_scores: share of ingress packets with an egress packet inside a
  delay window, minus the share expected by chance (A3).
"""
from __future__ import annotations

import numpy as np


def bin_matrix(times_per_session: list[list[float]], bin_s: float, horizon_s: float) -> np.ndarray:
    n_bins = max(1, int(np.ceil(horizon_s / bin_s)))
    out = np.zeros((len(times_per_session), n_bins))
    for row, times in enumerate(times_per_session):
        if not times:
            continue
        idx = (np.asarray(times) // bin_s).astype(int)
        idx = idx[(idx >= 0) & (idx < n_bins)]
        np.add.at(out[row], idx, 1.0)
    return out


def _standardise_rows(m: np.ndarray) -> np.ndarray:
    centred = m - m.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(centred, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return centred / norm


def lag_correlation_scores(
    ingress: list[list[float]],
    egress: list[list[float]],
    bin_s: float,
    horizon_s: float,
    max_lag_bins: int,
    ingress_horizon_s: float | None = None,
) -> np.ndarray:
    """Best standardised correlation over non-negative lags.

    Without ingress_horizon_s both sides are binned over horizon_s and the
    lagged windows shrink as the lag grows. With it, ingress is binned over
    its own (shorter) window and every lag compares it against an egress
    window of the same length, so ingress never carries the empty stretch
    that egress needs for delayed packets. Empty bins shared by all sessions
    would otherwise make impostor pairs correlate.
    """
    y = bin_matrix(egress, bin_s, horizon_s)
    best = np.full((len(ingress), y.shape[0]), -np.inf)
    if ingress_horizon_s is None:
        x = bin_matrix(ingress, bin_s, horizon_s)
        n_bins = x.shape[1]
        for lag in range(0, min(max_lag_bins, n_bins - 2) + 1):
            xs = _standardise_rows(x[:, : n_bins - lag])
            ys = _standardise_rows(y[:, lag:])
            np.maximum(best, xs @ ys.T, out=best)
        return best
    x = bin_matrix(ingress, bin_s, ingress_horizon_s)
    n_x = x.shape[1]
    xs = _standardise_rows(x)
    for lag in range(0, min(max_lag_bins, y.shape[1] - n_x) + 1):
        ys = _standardise_rows(y[:, lag : lag + n_x])
        np.maximum(best, xs @ ys.T, out=best)
    return best


def likelihood_ratio_scores(
    ingress: list[list[float]],
    egress: list[list[float]],
    density: np.ndarray,
    step_s: float,
    horizon_s: float,
    floor_rate: float = 1e-3,
) -> np.ndarray:
    """Score(i, j) = sum over egress packets y of j of
    log((c_ij + (f * X_i)(y)) / r_j), where f * X_i is ingress i's packet
    train convolved with the delay density (packets per second), r_j is
    egress j's mean rate, and c_ij = max(r_j - rate of X_i, floor_rate) is
    the part of j's rate left unexplained by i. Under this model the
    compensator terms of the two hypotheses cancel."""
    n_bins = max(1, int(np.ceil(horizon_s / step_s)))
    x = bin_matrix(ingress, step_s, horizon_s)
    size = n_bins + len(density)
    fft_len = 1 << (size - 1).bit_length()
    kernel = np.fft.rfft(density, fft_len)
    intensity = np.fft.irfft(np.fft.rfft(x, fft_len, axis=1) * kernel, fft_len, axis=1)[:, :n_bins]
    np.maximum(intensity, 0.0, out=intensity)
    x_rate = x.sum(axis=1) / horizon_s
    scores = np.zeros((len(ingress), len(egress)))
    for j, times in enumerate(egress):
        if not times:
            continue
        idx = (np.asarray(times) // step_s).astype(int)
        idx = idx[(idx >= 0) & (idx < n_bins)]
        r_j = max(len(idx) / horizon_s, floor_rate)
        c = np.maximum(r_j - x_rate, floor_rate)[:, None]
        scores[:, j] = np.log((c + intensity[:, idx]) / r_j).sum(axis=1)
    return scores


def window_scores(
    ingress: list[list[float]],
    egress: list[list[float]],
    window_s: float,
    horizon_s: float,
    grid_s: float = 0.001,
) -> np.ndarray:
    """Hit test on a grid of grid_s: an ingress packet at x counts as matched
    if egress j has a packet in the grid cells from x to x + window_s. The
    grid error is at most one cell at each end of the window."""
    n_in = len(ingress)
    lengths = np.array([len(x) for x in ingress])
    owner = np.repeat(np.arange(n_in), lengths)
    flat = np.concatenate([np.asarray(x, dtype=float) for x in ingress]) if lengths.sum() else np.zeros(0)
    n_cells = int(np.ceil((horizon_s + window_s) / grid_s)) + 2
    lo = np.clip((flat / grid_s).astype(np.int64), 0, n_cells - 1)
    hi = np.clip(((flat + window_s) / grid_s).astype(np.int64) + 1, 0, n_cells - 1)
    safe_len = np.maximum(lengths, 1)
    scores = np.zeros((n_in, len(egress)))
    for j, times in enumerate(egress):
        chance = 1.0 - np.exp(-len(times) / horizon_s * window_s)
        if len(times) == 0 or len(flat) == 0:
            scores[:, j] = -chance
            continue
        cells = np.clip((np.asarray(times, dtype=float) / grid_s).astype(np.int64), 0, n_cells - 1)
        cumulative = np.concatenate(([0], np.cumsum(np.bincount(cells, minlength=n_cells))))
        hit = (cumulative[hi] - cumulative[lo]) > 0
        share = np.bincount(owner, weights=hit, minlength=n_in) / safe_len
        share[lengths == 0] = 0.0
        scores[:, j] = share - chance
    return scores
