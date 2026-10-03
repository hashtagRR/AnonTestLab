"""Closed-form predictions for the binned-count correlation attacker, so a
run can report predicted values next to measured ones.

For a true pair the expected per-bin correlation between the observed
entry-side counts and the exit-side counts factorizes as

    r = policy_factor * delay_factor * cover_factor

(delay factor after Danezis, PET 2004, in binned form). Over B bins the
attacker's signal is about sqrt(B) * r, giving fixed-FPR linkability
Phi(signal - z_{alpha/m}) with a Bonferroni allowance for m lags, and
confident linkage Phi(signal / 2 - ln K / signal) with
K = psi (1 - base_rate) / ((1 - psi) base_rate).

These are large-sample Gaussian approximations. Traffic enters through the
mean m and the index of dispersion D = Var / m of the real cells per bin
(D = 1 for Poisson, larger for bursty traffic), measured from the
configured generator. With bursts that are short against a bin, the split
factors become
    i.i.d.       1 / sqrt(1 + (1 - p) / (p D))
    round-robin  1 / sqrt(1 + k^2 / (12 m D))
    batch        sqrt(p / (1 + (1 - p) m / D))
and the delay factor is divided by sqrt((1 - 1/D) Q2 + 1/D), where Q2 is
the summed square of the per-bin landing probabilities of one cell (the
cells of a burst leave together and are delayed independently). All reduce
to the Poisson forms at D = 1. The latency split policy has no closed form
here and is reported as NaN.
"""
from __future__ import annotations

import math
import random
from itertools import combinations
from statistics import NormalDist

import numpy as np

from .adversary import attacks
from .adversary.delay_model import sample_added_delay
from .emulator.splitting import LegScheduler
from .traffic import get_generator

_N = NormalDist()


def delay_factors(config, bin_s: float, max_lag_bins: int, n: int = 400_000, seed: int = 0) -> np.ndarray:
    """kappa(lag) for lag = 0..max_lag_bins: the chance that a packet sent at a
    uniform point of an entry bin leaves in the exit bin `lag` bins later."""
    rng = np.random.default_rng(seed)
    offset = rng.uniform(0.0, bin_s, n) + sample_added_delay(config, n, rng)
    lags = np.floor(offset / bin_s).astype(int)
    counts = np.bincount(lags[(lags >= 0) & (lags <= max_lag_bins)], minlength=max_lag_bins + 1)
    return counts[: max_lag_bins + 1] / n


def delay_spread(config, bin_s: float, max_lag_bins: int, n_offsets: int = 200, n: int = 4000,
                 seed: int = 0) -> float:
    """Q2: the expected sum over exit bins of the squared chance that one cell,
    sent at a uniform point of an entry bin, leaves in that bin. Cells of one
    burst share the send point and are delayed independently."""
    rng = np.random.default_rng(seed)
    total = 0.0
    for u in rng.uniform(0.0, bin_s, n_offsets):
        lags = np.floor((u + sample_added_delay(config, n, rng)) / bin_s).astype(int)
        q = np.bincount(lags - lags.min()) / n
        total += float(np.sum(q**2))
    return total / n_offsets


def traffic_moments(config, bin_s: float, seconds: float = 4000.0, seed: int = 0) -> tuple[float, float]:
    """Mean real cells per bin and their index of dispersion for the configured
    traffic generator (exactly lambda w and 1 for Poisson)."""
    if config.real_traffic_distribution == "poisson" or config.real_rate <= 0:
        return config.real_rate * bin_s, 1.0
    gen = get_generator(config.real_traffic_distribution, config.real_rate,
                        burst_mean_cells=config.burst_mean_cells, burst_gap_ms=config.burst_gap_ms)
    times = np.asarray(gen.emission_times(random.Random(seed), seconds))
    n_bins = int(seconds / bin_s)
    counts = np.bincount((times / bin_s).astype(int), minlength=n_bins)[:n_bins]
    m = float(counts.mean())
    return m, (float(counts.var()) / m if m > 0 else 1.0)


def policy_factor(
    policy: str, p: float, num_legs: int, cells_per_bin: float, batch_mean_s: float, bin_s: float,
    dispersion: float = 1.0,
) -> float:
    """Correlation between the counts of an observed share p of the flow and
    the whole flow, in the same bin, for counts with the given index of
    dispersion (1 for Poisson)."""
    if p >= 1.0:
        return 1.0
    if p <= 0.0:
        return 0.0
    d = max(dispersion, 1e-12)
    if policy in ("iid", "random"):
        return 1.0 / math.sqrt(1.0 + (1.0 - p) / (p * d))
    if policy == "round_robin":
        # rounding error of a deterministic interleave, variance about 1/12 per bin
        return 1.0 / math.sqrt(1.0 + num_legs**2 / (12.0 * max(cells_per_bin, 1e-12) * d))
    if policy == "batch":
        if batch_mean_s < 5 * bin_s:
            return float("nan")  # the closed form assumes batches much longer than a bin
        return math.sqrt(p / (1.0 + (1.0 - p) * cells_per_bin / d))
    return float("nan")


def observed_variance(policy: str, p: float, cells_per_bin: float, dispersion: float = 1.0) -> float:
    """Variance of the observed share's real-cell count per bin, in cells
    squared, for the same policies as policy_factor (other policies use the
    i.i.d. value)."""
    m, d = cells_per_bin, max(dispersion, 1e-12)
    if p >= 1.0:
        return m * d
    if policy == "round_robin":
        return p * p * m * d + 1.0 / 12.0
    if policy == "batch":
        return p * m * d + p * (1.0 - p) * m * m
    return p * m * (1.0 + p * (d - 1.0))


def cover_factor(policy: str, p: float, cells_per_bin: float, dispersion: float, cover_per_bin: float) -> float:
    """Correlation loss from independent Poisson cover seen on the entry side
    only. Cover is split over the legs like real cells, so the observed share
    p carries p * cover_per_bin cover cells per bin next to its real counts."""
    if cover_per_bin <= 0:
        return 1.0
    v = observed_variance(policy, p, cells_per_bin, dispersion)
    return math.sqrt(v / (v + p * cover_per_bin)) if v > 0 else 0.0


def observed_share(config) -> float:
    weights = config.split_weights or [1.0] * config.num_paths
    legs = config.observed_legs if config.observed_legs is not None else range(config.num_paths)
    return sum(weights[i] for i in legs) / sum(weights)


def _max_of_normals(m: int, n: int = 200_000, seed: int = 0) -> tuple[float, float]:
    """Mean and standard deviation of the maximum of m independent standard
    normals: the impostor score of a lag search over m lags, in units of the
    per-lag null standard deviation."""
    draws = np.random.default_rng(seed).standard_normal((n, m)).max(axis=1)
    return float(draws.mean()), float(draws.std())


def _confident_cut(mu_true: float, mu_imp: float, sd_imp: float, log_k: float) -> float:
    """The cut confident_linkage would choose from normal fits with these
    parameters (true-score standard deviation 1)."""
    grid = np.linspace(mu_imp, max(mu_true + 8.0, mu_imp + 12 * sd_imp), 20001)
    log_lr = -0.5 * (grid - mu_true) ** 2 + 0.5 * ((grid - mu_imp) / sd_imp) ** 2 + math.log(sd_imp)
    above = np.nonzero(log_lr >= log_k)[0]
    return float(grid[above[0]]) if len(above) else math.inf


def simulated_scores(config, lag_max_s: float, n_flows: int = 100, seed: int = 0) -> dict[float, dict[str, float]]:
    """Score moments of the lag-aware correlator on flows drawn from the
    configured traffic generator, split with the configured policy and
    delayed cell by cell with the configured mixing delay, scored with the
    suite's own code (no relays, no training). Per bin width: impostor
    mean and standard deviation, true-pair mean and standard deviation.

    The closed-form null (maximum of independent N(0, 1/B) lag scores)
    ignores the autocorrelation of the binned counts. Bursts that straddle
    bins, and the smearing of each burst by the delay, correlate
    neighbouring bins on both sides, which widens the null (Bartlett) and
    correlates the lag scores; this calibration captures both. Independent
    Poisson cover is added on the entry side only, assigned to the legs by
    the same scheduler and in the same time order as the emulator sends it."""
    gen = get_generator(config.real_traffic_distribution, config.real_rate,
                        burst_mean_cells=config.burst_mean_cells, burst_gap_ms=config.burst_gap_ms)
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    observed = set(config.observed_legs) if config.observed_legs is not None else set(range(config.num_paths))
    ingress, egress = [], []
    for _ in range(n_flows):
        t = np.asarray(gen.emission_times(rng, config.duration_s))
        sched = LegScheduler(
            config.split_strategy if config.num_paths > 1 else "round_robin", config.num_paths,
            weights=config.split_weights, batch_mean_s=config.split_batch_mean_s,
            leg_rtt_s=[ms / 1000.0 for ms in config.split_leg_rtt_ms] if config.split_leg_rtt_ms else None,
            leg_window=config.split_leg_window,
        )
        cover = (np.sort(nrng.uniform(0.0, config.duration_s, nrng.poisson(config.cover_rate * config.duration_s)))
                 if config.cover_rate > 0 else np.zeros(0))
        times = np.concatenate([t, cover])
        is_real = np.concatenate([np.ones(len(t), bool), np.zeros(len(cover), bool)])
        order = np.argsort(times, kind="stable")
        on_leg = np.zeros(len(times), bool)
        for i in order:
            on_leg[i] = sched.assign(float(times[i]), rng) in observed
        seen = on_leg[is_real]
        entry = np.sort(times[on_leg])
        leaving = t if config.egress_observation == "merged" else t[seen]
        ingress.append(entry.tolist())
        egress.append(np.sort(leaving + sample_added_delay(config, len(leaving), nrng)).tolist())
    out = {}
    off = ~np.eye(n_flows, dtype=bool)
    for w in config.suite_bin_widths_s:
        scores = attacks.lag_correlation_scores(ingress, egress, w, config.duration_s + lag_max_s,
                                                math.ceil(lag_max_s / w), config.duration_s)
        true, imp = np.diag(scores), scores[off]
        out[w] = {"imp_mean": float(imp.mean()), "imp_sd": float(imp.std()),
                  "true_mean": float(true.mean()), "true_sd": float(true.std())}
    return out


def predict(config, fpr: float = 1e-3, psi: float = 0.9, base_rate: float = 1e-4) -> dict[str, float]:
    """Predicted values for the lag-aware correlator (a1) at each bin width of
    the correlation suite, for the configured observed legs, computed the way
    the suite measures them. The true-pair level is the closed-form r. The
    impostor distribution and the spread of true-pair scores come from
    simulated_scores(); mu_hat is (r - impostor mean) / impostor sd, and
    TPR at FPR and confident linkage use normal fits to both, as the suite's
    confident-linkage metric does. `model_*_mu_hat_gaussian` keeps the fully
    closed-form value (true score N(sqrt(B) r, 1), impostor the maximum over
    the searched lags of independent N(0, 1) draws), which is accurate for
    Poisson traffic and too optimistic for bursty traffic. `model_*_r_sim`
    is the simulated true-pair level, a check on the closed-form r, and
    `model_*_mu_hat_sim` the signal computed from it (fully calibrated)."""
    lam = config.real_rate
    p = observed_share(config)
    log_k = math.log(psi * (1 - base_rate) / ((1 - psi) * base_rate))
    lag_max_s = config.suite_lag_max_s
    if lag_max_s is None:
        p99 = float(np.quantile(sample_added_delay(config, 200_000, np.random.default_rng(0)), 0.99))
        lag_max_s = max(2.0, p99) + 0.5
    policy = config.split_strategy if config.num_paths > 1 else "iid"
    out = {"model_observed_share": p}
    sim = simulated_scores(config, lag_max_s)
    for w in config.suite_bin_widths_s:
        lags = math.ceil(lag_max_s / w)
        bins = max(config.duration_s / w, 2.0)  # every lag compares the full flow window
        kappa = delay_factors(config, w, lags)
        m, d = traffic_moments(config, w)
        burst = 1.0 if d == 1.0 else 1.0 / math.sqrt((1.0 - 1.0 / d) * delay_spread(config, w, lags) + 1.0 / d)
        gamma = policy_factor(policy, p, config.num_paths, m, config.split_batch_mean_s, w, d)
        # independent Poisson cover on the observed legs adds variance p c w next to their real variance
        cover = cover_factor(policy, p, m, d, config.cover_rate * w) if lam > 0 else 0.0
        r = gamma * float(kappa.max()) * burst * cover
        out[f"model_dispersion_w{w}"] = d
        mu_true = math.sqrt(bins) * r
        mu_imp, sd_imp = _max_of_normals(lags + 1)
        prefix = f"model_a1_w{w}"
        null = sim[w]
        out[f"{prefix}_r"] = r
        out[f"{prefix}_r_sim"] = null["true_mean"]
        out[f"{prefix}_imp_mean"] = null["imp_mean"]
        out[f"{prefix}_imp_sd"] = null["imp_sd"]
        out[f"{prefix}_mu_hat_gaussian"] = (mu_true - mu_imp) / sd_imp
        if not null["imp_sd"] > 0:  # too few bins for a usable null (very short flows)
            for key in ("mu_hat", "mu_hat_sim", f"tpr_at_fpr_{fpr}", f"lpsi_{psi}_br_{base_rate}"):
                out[f"{prefix}_{key}"] = float("nan")
            continue
        out[f"{prefix}_mu_hat"] = (r - null["imp_mean"]) / null["imp_sd"]
        out[f"{prefix}_mu_hat_sim"] = (null["true_mean"] - null["imp_mean"]) / null["imp_sd"]
        if math.isnan(r):
            out[f"{prefix}_tpr_at_fpr_{fpr}"] = out[f"{prefix}_lpsi_{psi}_br_{base_rate}"] = float("nan")
            continue
        # scores in units of the true-pair standard deviation, as _confident_cut expects
        # floor: with no added delay a full observation reproduces the counts and
        # the simulated spread collapses, which would make the fits degenerate
        sd_true = max(null["true_sd"], 0.1 * null["imp_sd"], 1e-9)
        t_mu, i_mu, i_sd = r / sd_true, null["imp_mean"] / sd_true, null["imp_sd"] / sd_true
        out[f"{prefix}_tpr_at_fpr_{fpr}"] = 1 - _N.cdf(i_mu + _N.inv_cdf(1 - fpr) * i_sd - t_mu)
        cut_psi = _confident_cut(t_mu, i_mu, i_sd, log_k) if t_mu > i_mu else math.inf
        out[f"{prefix}_lpsi_{psi}_br_{base_rate}"] = 0.0 if math.isinf(cut_psi) else 1 - _N.cdf(cut_psi - t_mu)
    return out


def coupled_risk(link_prob, weights: list[float], f_guard: float, f_exit: float) -> float:
    """Probability that one flow is linked (model derivation, Proposition 1):
    f_exit * sum over non-empty sets S of compromised legs of
    P(S) * link_prob(p_S), with legs compromised independently."""
    k = len(weights)
    total = sum(weights)
    risk = 0.0
    for size in range(1, k + 1):
        for legs in combinations(range(k), size):
            p_s = sum(weights[i] for i in legs) / total
            risk += f_guard**size * (1 - f_guard) ** (k - size) * link_prob(p_s)
    return f_exit * risk


def power_mean_ratio(weights: list[float], tail_index: float) -> float:
    """Duration-averaged single-leg risk of a split relative to one path under
    Pareto flow durations (model derivation, Proposition 4): sum of p_i^a."""
    total = sum(weights)
    return sum((w / total) ** tail_index for w in weights)
