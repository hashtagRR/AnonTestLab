from __future__ import annotations

import random

import numpy as np

from . import decision, features, observation
from .base import Adversary, AdversaryResult, SimulationContext


class GlobalPassiveObserver(Adversary):
    """A global observer who sees packet timing at every observed
    session's entry and exit hop, but not packet contents. Composes three
    swappable stages: observation (bin raw timestamps), feature
    extraction (turn two time series into a score), decision (turn scores
    into a verdict: accuracy, TPR@FPR, AUC, precision/recall). Fed real
    measured timestamps when running on the emulator."""

    name = "global_observer"

    def __init__(
        self,
        bin_size: float = 0.05,
        classifier: str = "pearson",
        threshold: float = 0.7,
        fpr_targets: tuple[float, ...] = (0.1, 0.01, 0.001),
    ):
        self.bin_size = bin_size
        self.classifier = classifier
        self.threshold = threshold
        self.fpr_targets = fpr_targets

    @classmethod
    def from_config(cls, config) -> "GlobalPassiveObserver":
        return cls(
            bin_size=getattr(config, "observer_bin_width_ms", 50.0) / 1000.0,
            classifier=getattr(config, "observer_classifier", "pearson"),
            threshold=getattr(config, "observer_threshold", 0.7),
        )

    def attack(self, ctx: SimulationContext, rng: random.Random) -> AdversaryResult:
        sessions = ctx.sessions
        session_ids = list(sessions.keys())
        n = len(session_ids)
        if n == 0:
            return AdversaryResult(self.name, 0, {"correlation_success_rate": float("nan")})

        max_t = max(
            (t for obs in sessions.values() for t in (obs.ingress_times + obs.egress_times)),
            default=0.0,
        )
        n_bins = max(1, int(max_t // self.bin_size) + 1)

        ingress = np.stack(
            [observation.bin_counts(sessions[sid].ingress_times, self.bin_size, n_bins) for sid in session_ids]
        )
        egress = np.stack(
            [observation.bin_counts(sessions[sid].egress_times, self.bin_size, n_bins) for sid in session_ids]
        )

        extractor = features.get_feature_extractor(self.classifier)
        scores = extractor(ingress, egress)
        metrics = decision.evaluate_scores(scores, self.threshold, self.fpr_targets)

        return AdversaryResult(name=self.name, n_sessions=n, metrics=metrics)
