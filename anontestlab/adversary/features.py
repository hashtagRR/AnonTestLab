"""Turns a pair of per-session time-series matrices into a score matrix
(ingress session i vs egress session j), a swappable "classifier"."""
from __future__ import annotations

import numpy as np


def pearson_score_matrix(ingress: np.ndarray, egress: np.ndarray) -> np.ndarray:
    n = ingress.shape[0]
    scores = np.corrcoef(ingress, egress)[:n, n:]
    return np.nan_to_num(scores, nan=-1.0)


FEATURE_EXTRACTORS = {"pearson": pearson_score_matrix}


def get_feature_extractor(name: str):
    try:
        return FEATURE_EXTRACTORS[name]
    except KeyError:
        raise ValueError(
            f"unknown classifier type '{name}', available: {sorted(FEATURE_EXTRACTORS)}"
        ) from None
