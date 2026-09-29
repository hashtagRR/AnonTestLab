"""Runs the training-free correlation attackers side by side on the same
observations and reports, for each one, confident linkage, TPR at fixed
FPR and the signal estimate. All attackers share one calibration/test split
of the sessions, so their results are paired.

Attacker ids:
  a0_w<bin>          zero-lag binned-count correlation
  a1_w<bin>          lag-aware binned-count correlation (non-negative lags)
  a2                 likelihood-ratio attacker with the known delay density
  a3_q<quantile>     timing-window matcher, window = delay quantile + floor

The score matrices and the split are returned as artifacts so later
analysis (strongest-attacker selection, other threshold rules) does not
need a rerun.
"""
from __future__ import annotations

import math
import random

import numpy as np

from ..metrics.stats import confident_linkage, roc_auc, signal_estimate, tpr_at_fpr_detail
from . import attacks, delay_model
from .base import Adversary, AdversaryResult, SimulationContext


def _off_diagonal(m: np.ndarray) -> np.ndarray:
    return m[~np.eye(m.shape[0], dtype=bool)]


class CorrelationSuite(Adversary):
    name = "correlation_suite"

    def __init__(self, config):
        self.config = config
        self.bin_widths_s = list(config.suite_bin_widths_s)
        self.attackers = set(config.suite_attackers)
        self.psi = list(config.suite_psi)
        self.base_rates = list(config.suite_base_rates)
        self.fpr_targets = list(config.suite_fpr_targets)
        self.calibration_fraction = config.observer_calibration_fraction or 0.5
        self.window_quantiles = list(config.suite_window_quantiles)
        self.latency_floor_s = config.suite_latency_floor_ms / 1000.0
        self.lr_step_s = config.suite_lr_step_ms / 1000.0
        if config.suite_lag_max_s is not None:
            self.lag_max_s = config.suite_lag_max_s
        else:
            p99 = delay_model.delay_quantiles(config, (0.99,))[0.99]
            self.lag_max_s = max(2.0, p99) + 0.5

    @classmethod
    def from_config(cls, config) -> CorrelationSuite:
        return cls(config)

    def _scores(self, ingress, egress, horizon) -> dict[str, np.ndarray]:
        out = {}
        flow = self.config.duration_s
        for w in self.bin_widths_s:
            if "a0" in self.attackers:
                out[f"a0_w{w}"] = attacks.lag_correlation_scores(ingress, egress, w, horizon, 0, flow)
            if "a1" in self.attackers:
                lags = math.ceil(self.lag_max_s / w)
                out[f"a1_w{w}"] = attacks.lag_correlation_scores(ingress, egress, w, horizon, lags, flow)
        if "a2" in self.attackers:
            density = delay_model.delay_density(self.config, self.lr_step_s)
            out["a2"] = attacks.likelihood_ratio_scores(ingress, egress, density, self.lr_step_s, horizon)
        if "a3" in self.attackers:
            quantiles = delay_model.delay_quantiles(self.config, tuple(self.window_quantiles))
            for q, value in quantiles.items():
                out[f"a3_q{q}"] = attacks.window_scores(ingress, egress, value + self.latency_floor_s, horizon)
        return out

    def attack(self, ctx: SimulationContext, rng: random.Random) -> AdversaryResult:
        sids = sorted(ctx.sessions)
        n = len(sids)
        if n < 4:
            return AdversaryResult(self.name, n, {"suite_sessions": n})
        # Every session is binned over the same configured window: the flow
        # duration plus the lag range, since exit traffic trails by the added
        # delay. A shared horizon taken from the latest timestamp would let one
        # overrunning session pad every other series with trailing zeros, and
        # that common on/off shape makes impostor pairs correlate. The binned
        # attackers use only the flow duration on the ingress side for the
        # same reason (see attacks.lag_correlation_scores).
        horizon = self.config.duration_s + self.lag_max_s
        raw_in = [ctx.sessions[s].ingress_times for s in sids]
        raw_out = [ctx.sessions[s].egress_times for s in sids]
        ingress = [[t for t in obs if 0.0 <= t < horizon] for obs in raw_in]
        egress = [[t for t in obs if 0.0 <= t < horizon] for obs in raw_out]
        dropped = sum(len(a) for a in raw_in + raw_out) - sum(len(a) for a in ingress + egress)
        overrun = sum(
            1 for a, b in zip(raw_in, raw_out) if any(t >= horizon for t in a) or any(t >= horizon for t in b)
        )

        order = np.random.default_rng(rng.randrange(2**32)).permutation(n)
        n_cal = min(max(2, round(self.calibration_fraction * n)), n - 2)
        cal, test = np.sort(order[:n_cal]), np.sort(order[n_cal:])

        metrics: dict[str, float] = {"suite_calibration_sessions": len(cal), "suite_test_sessions": len(test),
                                     "suite_lag_max_s": self.lag_max_s, "suite_horizon_s": horizon,
                                     "suite_overrun_sessions": overrun, "suite_dropped_timestamps": dropped}
        artifacts: dict[str, object] = {"session_ids": np.asarray(sids), "calibration_idx": cal, "test_idx": test}
        # Raw observations as flat arrays plus offsets, so a run can be
        # rescored offline without rerunning the relays.
        for side, series in (("ingress", raw_in), ("egress", raw_out)):
            artifacts[f"{side}_times"] = np.asarray([t for obs in series for t in obs], dtype=float)
            artifacts[f"{side}_offsets"] = np.cumsum([0] + [len(obs) for obs in series])
        for attacker, scores in self._scores(ingress, egress, horizon).items():
            artifacts[f"scores_{attacker}"] = scores
            cal_scores = scores[np.ix_(cal, cal)]
            test_scores = scores[np.ix_(test, test)]
            true_cal, imp_cal = np.diag(cal_scores), _off_diagonal(cal_scores)
            true_test, imp_test = np.diag(test_scores), _off_diagonal(test_scores)
            detail = tpr_at_fpr_detail(true_test, imp_cal, self.fpr_targets, test_impostor_scores=imp_test)
            for fpr, point in detail.items():
                metrics[f"{attacker}_tpr_at_fpr_{fpr}"] = point.tpr
                metrics[f"{attacker}_realized_fpr_{fpr}"] = point.realized_fpr
                metrics[f"{attacker}_fpr_support_{fpr}"] = point.expected_exceedances
            for psi in self.psi:
                for br in self.base_rates:
                    metrics[f"{attacker}_lpsi_{psi}_br_{br}"] = confident_linkage(true_cal, imp_cal, true_test, psi, br)
            metrics[f"{attacker}_mu_hat"] = signal_estimate(true_test, imp_test)
            metrics[f"{attacker}_auc"] = roc_auc(list(true_test), list(imp_test))
        if "a1" in self.attackers:
            from ..model import predict  # imported here: model imports this package's delay model

            psi = self.psi[0] if self.psi else 0.9
            base_rate = self.base_rates[0] if self.base_rates else 1e-4
            fpr = self.fpr_targets[0] if self.fpr_targets else 1e-3
            metrics.update(predict(self.config, fpr=fpr, psi=psi, base_rate=base_rate))
        return AdversaryResult(self.name, n, metrics, artifacts)
