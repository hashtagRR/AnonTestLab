"""Turns a score matrix into a verdict: matching accuracy plus the
standard detection-problem metrics (TPR@FPR, AUC, precision/recall)."""
from __future__ import annotations

import numpy as np

from ..metrics.stats import precision_recall_at_threshold, roc_auc, tpr_at_fpr


def evaluate_scores(
    scores: np.ndarray, threshold: float, fpr_targets: tuple[float, ...]
) -> dict[str, float]:
    n = scores.shape[0]
    if n == 0:
        metrics = {"correlation_success_rate": float("nan"), "auc": float("nan"),
                   "precision": float("nan"), "recall": float("nan")}
        metrics.update({f"tpr_at_fpr_{fpr}": float("nan") for fpr in fpr_targets})
        return metrics

    predicted = scores.argmax(axis=1)
    correct = sum(1 for i in range(n) if predicted[i] == i)
    true_scores = [scores[i, i] for i in range(n)]
    impostor_scores = [scores[i, j] for i in range(n) for j in range(n) if i != j]

    metrics = {"correlation_success_rate": correct / n}
    for fpr, tpr in tpr_at_fpr(true_scores, impostor_scores, list(fpr_targets)).items():
        metrics[f"tpr_at_fpr_{fpr}"] = tpr
    metrics["auc"] = roc_auc(true_scores, impostor_scores)
    precision, recall = precision_recall_at_threshold(true_scores, impostor_scores, threshold)
    metrics["precision"] = precision
    metrics["recall"] = recall
    return metrics
