"""Generic statistics helpers: Wilson-score confidence intervals and the
standard TPR-at-fixed-FPR reporting used for matching/detection problems.
Both are textbook techniques, independent of any particular network design.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson-score interval for a binomial proportion.

    Returns (center, half_width) so callers can report `center +/- half_width`.
    """
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half_width = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return center, half_width


@dataclass(frozen=True)
class FprPoint:
    """One operating point. A pair is flagged as a match iff its score is
    strictly greater than `cut`."""

    tpr: float
    cut: float
    realized_fpr: float  # measured on the test impostors if given, else on the calibration ones
    expected_exceedances: float  # fpr * calibration impostor count: how much tail supports the cut


def cut_at_fpr(impostor_scores: np.ndarray, fpr: float) -> float:
    """Conservative threshold: the smallest cut such that the fraction of
    impostor scores strictly above it is <= fpr, even when scores tie.
    Ties at the boundary count as non-matches, so the realized FPR stays
    at or below the target."""
    impostor = np.sort(np.asarray(impostor_scores, dtype=float))[::-1]
    n = len(impostor)
    k = math.floor(fpr * n + 1e-9)  # impostors allowed above the cut
    if k >= n:
        return -math.inf
    return float(impostor[k])


def tpr_at_fpr_detail(
    true_scores: list[float],
    calibration_impostor_scores: list[float],
    fpr_targets: list[float],
    test_impostor_scores: list[float] | None = None,
) -> dict[float, FprPoint]:
    """TPR at each target FPR, with the cut chosen on the calibration
    impostors. Passing separate test impostors (and test true scores)
    gives a held-out estimate instead of an in-sample one."""
    cal = np.asarray(calibration_impostor_scores, dtype=float)
    true = np.asarray(true_scores, dtype=float)
    test_imp = cal if test_impostor_scores is None else np.asarray(test_impostor_scores, dtype=float)
    result = {}
    for fpr in fpr_targets:
        if len(cal) == 0 or len(true) == 0:
            result[fpr] = FprPoint(float("nan"), float("nan"), float("nan"), 0.0)
            continue
        cut = cut_at_fpr(cal, fpr)
        realized = float(np.mean(test_imp > cut)) if len(test_imp) else float("nan")
        result[fpr] = FprPoint(float(np.mean(true > cut)), cut, realized, fpr * len(cal))
    return result


def tpr_at_fpr(
    true_scores: list[float], impostor_scores: list[float], fpr_targets: list[float]
) -> dict[float, float]:
    """Standard matching-problem evaluation: for each target false-positive
    rate, find the conservative cut on the impostor distribution (see
    `cut_at_fpr`), then report the true-positive rate above it.
    """
    detail = tpr_at_fpr_detail(true_scores, impostor_scores, fpr_targets)
    return {fpr: point.tpr for fpr, point in detail.items()}


@dataclass(frozen=True)
class PairedEffect:
    """Paired seed-level comparison of one metric between a reference and
    a treatment condition."""

    mean_delta: float  # treatment - reference
    ci_low: float
    ci_high: float
    n_pairs: int
    classification: str  # "no_meaningful_effect" | "meaningful_effect" | "inconclusive"


def paired_bootstrap_delta(
    reference: list[float],
    treatment: list[float],
    *,
    margin: float = 0.05,
    resamples: int = 10000,
    confidence: float = 0.95,
    seed: int = 0,
) -> PairedEffect:
    """Bootstrap the mean of the per-seed differences (seeds paired by
    position) and classify it with an explicit equivalence rule:

    - no_meaningful_effect: the whole CI lies inside (-margin, +margin)
    - meaningful_effect: the CI excludes zero and |mean| >= margin
    - inconclusive: anything else. A CI that merely includes zero is not
      evidence of no effect.
    """
    ref = np.asarray(reference, dtype=float)
    treat = np.asarray(treatment, dtype=float)
    if ref.shape != treat.shape:
        raise ValueError(f"paired inputs differ in length: {ref.shape} vs {treat.shape}")
    keep = ~(np.isnan(ref) | np.isnan(treat))
    diffs = treat[keep] - ref[keep]
    if len(diffs) < 2:
        raise ValueError("paired bootstrap needs at least two complete pairs")
    rng = np.random.default_rng(seed)
    boots = diffs[rng.integers(0, len(diffs), size=(resamples, len(diffs)))].mean(axis=1)
    alpha = (1 - confidence) / 2
    lo, hi = (float(q) for q in np.quantile(boots, [alpha, 1 - alpha]))
    mean = float(diffs.mean())
    if lo > -margin and hi < margin:
        label = "no_meaningful_effect"
    elif (lo > 0 or hi < 0) and abs(mean) >= margin:
        label = "meaningful_effect"
    else:
        label = "inconclusive"
    return PairedEffect(mean, lo, hi, len(diffs), label)


def roc_auc(true_scores: list[float], impostor_scores: list[float]) -> float:
    """AUC via the pairwise (Mann-Whitney U) definition: the probability a
    random true-pair score outranks a random impostor-pair score, with
    half credit for ties. Avoids needing a full ROC sweep or a new
    dependency for score counts in the sizes this project deals with.
    """
    if not true_scores or not impostor_scores:
        return float("nan")
    true_arr = np.asarray(true_scores)
    imp_arr = np.asarray(impostor_scores)
    greater = (true_arr[:, None] > imp_arr[None, :]).sum()
    ties = (true_arr[:, None] == imp_arr[None, :]).sum()
    return float((greater + 0.5 * ties) / (len(true_arr) * len(imp_arr)))


def precision_recall_at_threshold(
    true_scores: list[float], impostor_scores: list[float], threshold: float
) -> tuple[float, float]:
    """Precision/recall treating score >= threshold as a predicted match."""
    true_arr = np.asarray(true_scores)
    imp_arr = np.asarray(impostor_scores)
    tp = int(np.sum(true_arr >= threshold))
    fn = int(np.sum(true_arr < threshold))
    fp = int(np.sum(imp_arr >= threshold))
    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    return precision, recall


def confident_linkage(
    true_calibration: list[float],
    impostor_calibration: list[float],
    true_test: list[float],
    psi: float,
    base_rate: float,
) -> float:
    """Share of held-out true pairs that an attacker would accept with
    posterior probability at least psi, when a fraction base_rate of all
    candidate pairs are true pairs.

    True and impostor scores are each fitted with a normal distribution on
    the calibration sessions. The cut is the smallest score above the
    impostor mean at which the fitted likelihood ratio reaches
    K = psi (1 - base_rate) / ((1 - psi) base_rate). Unlike TPR at a fixed
    FPR, this gives no credit for chance-level matches when evidence is
    weak, which matters when results are averaged over many short flows."""
    t = np.asarray(true_calibration, dtype=float)
    imp = np.asarray(impostor_calibration, dtype=float)
    test = np.asarray(true_test, dtype=float)
    if len(t) < 2 or len(imp) < 2 or len(test) == 0:
        return float("nan")
    m1, s1 = float(t.mean()), max(float(t.std(ddof=1)), 1e-12)
    m0, s0 = float(imp.mean()), max(float(imp.std(ddof=1)), 1e-12)
    if m1 <= m0:
        return 0.0
    log_k = math.log(psi * (1 - base_rate) / ((1 - psi) * base_rate))
    grid = np.linspace(m0, max(m1 + 8 * s1, m0 + 12 * s0), 20001)
    log_lr = (
        -0.5 * ((grid - m1) / s1) ** 2 - math.log(s1)
        + 0.5 * ((grid - m0) / s0) ** 2 + math.log(s0)
    )
    above = np.nonzero(log_lr >= log_k)[0]
    if len(above) == 0:
        return 0.0
    return float(np.mean(test >= grid[above[0]]))


def signal_estimate(true_scores: list[float], impostor_scores: list[float]) -> float:
    """Separation of true and impostor scores in impostor standard deviations."""
    t = np.asarray(true_scores, dtype=float)
    imp = np.asarray(impostor_scores, dtype=float)
    if len(t) == 0 or len(imp) < 2:
        return float("nan")
    return float((t.mean() - imp.mean()) / max(imp.std(ddof=1), 1e-12))
