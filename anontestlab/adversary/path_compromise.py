from __future__ import annotations

import random

from ..metrics.stats import wilson_ci
from .base import Adversary, AdversaryResult, SimulationContext


class PathCompromiseAdversary(Adversary):
    """Independent-compromise Monte Carlo: if an adversary controls
    fraction f of relays (each relay compromised independently,
    Bernoulli(f)), what's the probability a session is fully
    deanonymizable: every node on (at least one of / all of) its
    path(s) is compromised? For a single k-hop path this is the textbook
    f^k; this generalizes it empirically to multi-path sessions.
    Deliberately independent-only; no correlated/shared-operator
    modeling in scope here."""

    name = "path_compromise"

    def __init__(self, compromised_fraction: float = 0.1, trials: int = 2000):
        self.compromised_fraction = compromised_fraction
        self.trials = trials

    @classmethod
    def from_config(cls, config) -> "PathCompromiseAdversary":
        return cls(compromised_fraction=config.compromised_fraction, trials=config.compromise_trials)

    def attack(self, ctx: SimulationContext, rng: random.Random) -> AdversaryResult:
        session_ids = list(ctx.session_paths.keys())
        n_sessions = len(session_ids)
        if n_sessions == 0 or self.trials == 0:
            return AdversaryResult(self.name, 0, {"full_compromise_rate": float("nan")})

        node_ids = ctx.node_ids
        full_count = 0
        any_count = 0
        total = 0

        for _ in range(self.trials):
            compromised = {node for node in node_ids if rng.random() < self.compromised_fraction}
            for sid in session_ids:
                paths = ctx.session_paths[sid]
                path_compromised = [all(node in compromised for node in path) for path in paths]
                full_count += all(path_compromised)
                any_count += any(path_compromised)
                total += 1

        full_center, full_hw = wilson_ci(full_count, total)
        any_center, any_hw = wilson_ci(any_count, total)

        return AdversaryResult(
            name=self.name,
            n_sessions=n_sessions,
            metrics={
                "full_compromise_rate": full_center,
                "full_compromise_ci95": full_hw,
                "any_path_compromise_rate": any_center,
                "any_path_compromise_ci95": any_hw,
                "compromise_trials": total,
            },
        )
