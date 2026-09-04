"""Generic statistics helpers: Wilson-score confidence intervals and the
standard TPR-at-fixed-FPR reporting used for matching/detection problems.
Both are textbook techniques, independent of any particular network design.
"""
from __future__ import annotations

import math

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


def tpr_at_fpr(
    true_scores: list[float], impostor_scores: list[float], fpr_targets: list[float]
) -> dict[float, float]:
    """Standard matching-problem evaluation: for each target false-positive
    rate, find the score threshold achieving it on the impostor distribution,
    then report the true-positive rate at that threshold.
    """
    impostor = np.sort(np.asarray(impostor_scores))[::-1]
    true = np.asarray(true_scores)
    n_impostor = len(impostor)
    result = {}
    for fpr in fpr_targets:
        if n_impostor == 0:
            result[fpr] = float("nan")
            continue
        k = max(1, int(round(fpr * n_impostor)))
        k = min(k, n_impostor)
        threshold = impostor[k - 1]
        tpr = float(np.mean(true >= threshold)) if len(true) else float("nan")
        result[fpr] = tpr
    return result


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
