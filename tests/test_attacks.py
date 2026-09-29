"""Training-free correlation attackers (adversary/attacks.py), the delay
model, the confident-linkage metric and the correlation_suite adversary.
The unit tests use synthetic traces with a known pairing; the last test
runs the suite on real relays."""
import random

import numpy as np
import pytest

from anontestlab.adversary import attacks, delay_model
from anontestlab.adversary.base import SessionObservation, SimulationContext
from anontestlab.adversary.correlation_suite import CorrelationSuite
from anontestlab.experiment import ExperimentConfig, run_experiment
from anontestlab.metrics.stats import confident_linkage, roc_auc

HORIZON = 60.0


def _poisson(rng, rate, horizon=HORIZON):
    return sorted(rng.uniform(0, horizon, rng.poisson(rate * horizon)))


def _pairs(n, rate, delay_fn, seed=0):
    """n independent Poisson flows; egress = ingress times plus a delay."""
    rng = np.random.default_rng(seed)
    ingress = [_poisson(rng, rate) for _ in range(n)]
    egress = [sorted(t + delay_fn(rng) for t in flow) for flow in ingress]
    return ingress, egress


def _auc(scores):
    n = scores.shape[0]
    off = scores[~np.eye(n, dtype=bool)]
    return roc_auc(list(np.diag(scores)), list(off))


def _config(**overrides):
    base = {"name": "t"}
    base.update(overrides)
    return ExperimentConfig(**base)


def test_lag_search_recovers_a_constant_shift_that_defeats_zero_lag():
    ingress, egress = _pairs(30, 8.0, lambda rng: 0.5)  # exactly two 0.25 s bins
    zero = attacks.lag_correlation_scores(ingress, egress, 0.25, HORIZON + 1, 0)
    lagged = attacks.lag_correlation_scores(ingress, egress, 0.25, HORIZON + 1, 4)
    assert _auc(lagged) > 0.99
    assert np.mean(np.diag(lagged)) > 0.99
    assert np.mean(np.diag(zero)) < 0.1


def test_best_lag_correlation_matches_the_delay_factor():
    # A 0.6 s shift covers 2.4 bins of 0.25 s: 60% of each bin's packets land
    # in one lagged bin, so the best-lag correlation is the kernel overlap 0.6
    # (model derivation, delay factor kappa at the best lag).
    ingress, egress = _pairs(40, 8.0, lambda rng: 0.6, seed=2)
    lagged = attacks.lag_correlation_scores(ingress, egress, 0.25, HORIZON + 1, 4)
    assert float(np.mean(np.diag(lagged))) == pytest.approx(0.6, abs=0.03)


def test_likelihood_ratio_attacker_separates_true_pairs_under_exponential_delay():
    config = _config(mix_strategy="exponential", mix_delay_ms=100.0, path_length=3)
    density = delay_model.delay_density(config, 0.01)
    rng_delay = np.random.default_rng(3)
    ingress, egress = _pairs(30, 8.0, lambda rng: rng_delay.exponential(0.1, 3).sum())
    scores = attacks.likelihood_ratio_scores(ingress, egress, density, 0.01, HORIZON + 5)
    assert _auc(scores) > 0.99
    assert np.all(np.diag(scores) > 0)


def test_window_matcher_is_near_zero_for_impostors():
    ingress, egress = _pairs(30, 8.0, lambda rng: rng.uniform(0.0, 0.05))
    scores = attacks.window_scores(ingress, egress, 0.07, HORIZON + 1)
    off = scores[~np.eye(30, dtype=bool)]
    assert abs(float(np.mean(off))) < 0.05
    assert float(np.mean(np.diag(scores))) > 0.3


def test_delay_model_means_match_the_mixing_settings():
    rng = np.random.default_rng(1)
    exp = delay_model.sample_added_delay(_config(mix_strategy="exponential", mix_delay_ms=50.0), 200_000, rng)
    assert exp.mean() == pytest.approx(0.15, rel=0.02)  # three hops of 50 ms mean
    const = delay_model.sample_added_delay(_config(mix_strategy="constant", mix_delay_ms=40.0), 1000, rng)
    assert np.allclose(const, 0.12)
    pool = _config(mix_strategy="pool", pool_interval_ms=200.0, pool_release_probability=1.0)
    assert delay_model.sample_added_delay(pool, 200_000, rng).mean() == pytest.approx(0.3, rel=0.02)
    assert np.all(delay_model.sample_added_delay(_config(), 100, rng) == 0)


def test_delay_density_integrates_to_one():
    density = delay_model.delay_density(_config(mix_strategy="exponential", mix_delay_ms=50.0), 0.005)
    assert density.sum() * 0.005 == pytest.approx(1.0, abs=1e-3)


def test_confident_linkage_rejects_weak_evidence_that_fixed_fpr_still_credits():
    rng = np.random.default_rng(5)
    impostors = rng.normal(0, 1, 20000)
    strong = rng.normal(8, 1, 200)
    weak = rng.normal(0.3, 1, 200)
    assert confident_linkage(strong[:100], impostors, strong[100:], 0.9, 1e-4) > 0.95
    assert confident_linkage(weak[:100], impostors, weak[100:], 0.9, 1e-4) == 0.0
    assert confident_linkage(rng.normal(-1, 1, 100), impostors, weak, 0.9, 1e-4) == 0.0


def test_confident_linkage_is_stricter_at_lower_base_rates():
    rng = np.random.default_rng(6)
    impostors = rng.normal(0, 1, 20000)
    true = rng.normal(4.5, 1, 400)
    common = confident_linkage(true[:200], impostors, true[200:], 0.9, 1e-2)
    rare = confident_linkage(true[:200], impostors, true[200:], 0.9, 1e-6)
    assert common > rare


def _suite_context(n, delay_s):
    ingress, egress = _pairs(n, 8.0, lambda rng: delay_s)
    sessions = {
        i: SessionObservation(session_id=i, ingress_times=list(ingress[i]), egress_times=list(egress[i]))
        for i in range(n)
    }
    return SimulationContext(sessions=sessions, session_paths={}, node_ids=[])


def test_suite_reports_every_attacker_with_a_shared_split():
    config = _config(suite_bin_widths_s=[0.25, 1.0], suite_psi=[0.9], suite_base_rates=[1e-4],
                     suite_fpr_targets=[1e-3], observer_calibration_fraction=0.5)
    result = CorrelationSuite.from_config(config).attack(_suite_context(24, 0.4), random.Random(0))
    m = result.metrics
    for attacker in ("a0_w0.25", "a0_w1.0", "a1_w0.25", "a1_w1.0", "a2", "a3_q0.5", "a3_q0.95"):
        for key in ("lpsi_0.9_br_0.0001", "tpr_at_fpr_0.001", "mu_hat", "auc"):
            assert f"{attacker}_{key}" in m
        assert result.artifacts[f"scores_{attacker}"].shape == (24, 24)
    assert m["suite_calibration_sessions"] + m["suite_test_sessions"] == 24
    assert m["a1_w0.25_mu_hat"] > m["a0_w0.25_mu_hat"]  # a 0.4 s shift spans more than one 0.25 s bin


def test_suite_on_real_relays_writes_scores(tmp_path):
    config = _config(name="suite-live", seed=9, duration_s=4.0, grace_period_s=1.0, num_nodes=6,
                     num_sessions=8, path_length=3, real_rate=20.0, crypto_algorithm="aes256gcm",
                     adversaries=["correlation_suite"], suite_bin_widths_s=[0.25], suite_psi=[0.9],
                     suite_base_rates=[1e-4], suite_fpr_targets=[1e-3], observer_calibration_fraction=0.5)
    result = run_experiment(config, out_dir=tmp_path)
    assert result.metrics["delivery_rate"] == 1.0
    assert "a1_w0.25_lpsi_0.9_br_0.0001" in result.metrics
    saved = np.load(tmp_path / "correlation_suite.npz")
    assert saved["scores_a1_w0.25"].shape == (8, 8)


def test_an_overrunning_session_does_not_inflate_impostor_scores():
    config = _config(duration_s=HORIZON, suite_attackers=["a1"], suite_bin_widths_s=[0.25], suite_psi=[0.9],
                     suite_base_rates=[1e-4], suite_fpr_targets=[1e-3], suite_lag_max_s=2.5,
                     observer_calibration_fraction=0.5)
    ctx = _suite_context(24, 0.3)
    late = ctx.sessions[0]
    late.ingress_times = late.ingress_times + [t + 200.0 for t in late.ingress_times[:50]]
    result = CorrelationSuite.from_config(config).attack(ctx, random.Random(0))
    scores = result.artifacts["scores_a1_w0.25"]
    impostors = scores[~np.eye(24, dtype=bool)]
    assert result.metrics["suite_overrun_sessions"] == 1
    assert result.metrics["suite_dropped_timestamps"] == 50
    assert float(np.mean(impostors)) < 0.3


def test_ingress_window_without_trailing_padding_keeps_impostors_near_zero():
    # Flows fill [0, 40) and egress needs 2.5 s more for delayed packets.
    # Binning ingress over the padded window gives every session the same
    # empty tail, which on its own makes impostor pairs correlate.
    ingress, egress = _pairs(30, 40.0, lambda rng: rng.exponential(0.075), seed=4)
    ingress = [[t * 40.0 / HORIZON for t in flow] for flow in ingress]
    egress = [[t * 40.0 / HORIZON for t in flow] for flow in egress]
    padded = attacks.lag_correlation_scores(ingress, egress, 0.25, 42.5, 10)
    trimmed = attacks.lag_correlation_scores(ingress, egress, 0.25, 42.5, 10, 40.0)
    off = ~np.eye(30, dtype=bool)
    # With the empty tail removed, impostors sit at the chance level of a
    # maximum over 11 lags of 160-bin correlations, about 1.59 / sqrt(160).
    chance = 1.59 / np.sqrt(160)
    assert float(np.mean(trimmed[off])) == pytest.approx(chance, abs=0.02)
    assert float(np.mean(padded[off])) > chance + 0.1
    assert _auc(trimmed) > 0.99


def test_suite_saves_raw_observations_for_rescoring():
    config = _config(suite_attackers=["a1"], suite_bin_widths_s=[0.25], suite_psi=[0.9],
                     suite_base_rates=[1e-4], suite_fpr_targets=[1e-3], observer_calibration_fraction=0.5)
    ctx = _suite_context(8, 0.3)
    art = CorrelationSuite.from_config(config).attack(ctx, random.Random(0)).artifacts
    off = art["egress_offsets"]
    assert len(off) == 9
    assert list(art["egress_times"][off[3]:off[4]]) == ctx.sessions[3].egress_times
