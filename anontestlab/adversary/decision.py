"""Turns a score matrix into a verdict: matching accuracy plus the
standard detection-problem metrics (TPR@FPR, AUC, precision/recall)."""
from __future__ import annotations

import numpy as np

from ..metrics.stats import precision_recall_at_threshold, roc_auc, tpr_at_fpr_detail


def _off_diagonal(scores: np.ndarray) -> np.ndarray:
    return scores[~np.eye(scores.shape[0], dtype=bool)]


def evaluate_scores(
    scores: np.ndarray,
    threshold: float,
    fpr_targets: tuple[float, ...],
    calibration_fraction: float = 0.0,
    rng: np.random.Generator | None = None,
) -> dict[str, float]:
    """calibration_fraction == 0 keeps the in-sample estimate: the TPR@FPR
    cut is chosen on the same impostor pairs it's reported against.
    calibration_fraction > 0 splits sessions into disjoint calibration and
    test sets. The cut comes from calibration impostor pairs only, and TPR
    and realized FPR are read from the test sessions, so the threshold is
    never tuned on the pairs it's scored against."""
    n = scores.shape[0]
    if n == 0:
        metrics = {"correlation_success_rate": float("nan"), "auc": float("nan"),
                   "precision": float("nan"), "recall": float("nan")}
        metrics.update({f"tpr_at_fpr_{fpr}": float("nan") for fpr in fpr_targets})
        return metrics

    predicted = scores.argmax(axis=1)
    correct = sum(1 for i in range(n) if predicted[i] == i)
    true_scores = np.diag(scores)
    impostor_scores = _off_diagonal(scores)

    metrics = {"correlation_success_rate": correct / n}

    if calibration_fraction > 0 and n >= 4:
        rng = rng if rng is not None else np.random.default_rng(0)
        order = rng.permutation(n)
        n_cal = min(max(2, round(calibration_fraction * n)), n - 2)
        cal, test = order[:n_cal], order[n_cal:]
        detail = tpr_at_fpr_detail(
            np.diag(scores)[test],
            _off_diagonal(scores[np.ix_(cal, cal)]),
            list(fpr_targets),
            test_impostor_scores=_off_diagonal(scores[np.ix_(test, test)]),
        )
        metrics["calibration_sessions"] = len(cal)
        metrics["test_sessions"] = len(test)
    else:
        detail = tpr_at_fpr_detail(true_scores, impostor_scores, list(fpr_targets))

    for fpr, point in detail.items():
        metrics[f"tpr_at_fpr_{fpr}"] = point.tpr
        metrics[f"realized_fpr_{fpr}"] = point.realized_fpr
        metrics[f"fpr_support_{fpr}"] = point.expected_exceedances
    metrics["auc"] = roc_auc(list(true_scores), list(impostor_scores))
    precision, recall = precision_recall_at_threshold(list(true_scores), list(impostor_scores), threshold)
    metrics["precision"] = precision
    metrics["recall"] = recall
    return metrics
