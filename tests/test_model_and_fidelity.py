"""Model predictions (anontestlab/model.py), wave mode and the fidelity
check. The model tests check the limiting cases written out in the model
derivation; the last two tests spawn real relays."""
import math
import random

import numpy as np
import pytest

from anontestlab import model
from anontestlab.experiment import ExperimentConfig, run_experiment
from anontestlab.experiment.config import PathSpec
from anontestlab.experiment.fidelity import run_fidelity


def _config(**overrides):
    base = {"name": "t"}
    base.update(overrides)
    return ExperimentConfig(**base)


def test_policy_factors():
    assert model.policy_factor("iid", 0.25, 4, 20.0, 2.0, 0.5) == pytest.approx(0.5)
    assert model.policy_factor("round_robin", 0.5, 2, 20.0, 2.0, 0.5) > 0.99
    assert model.policy_factor("batch", 0.5, 2, 20.0, 5.0, 0.5) == pytest.approx(math.sqrt(0.5 / 11.0))
    assert math.isnan(model.policy_factor("batch", 0.5, 2, 20.0, 1.0, 0.5))  # batches too short for the formula
    assert math.isnan(model.policy_factor("latency", 0.5, 2, 20.0, 2.0, 0.5))
    assert model.policy_factor("iid", 1.0, 2, 20.0, 2.0, 0.5) == 1.0


def test_delay_factor_of_a_constant_shift():
    config = _config(mix_strategy="constant", mix_delay_ms=200.0)  # 3 hops: 0.6 s
    kappa = model.delay_factors(config, 0.25, 4)
    assert kappa[2] == pytest.approx(0.6, abs=0.01)
    assert kappa[3] == pytest.approx(0.4, abs=0.01)
    assert kappa[0] == pytest.approx(0.0, abs=1e-9)


def test_coupled_risk_limits():
    f_g, f_x = 0.1, 0.2
    # every compromised leg links with certainty: the any-entry formula
    assert model.coupled_risk(lambda p: 1.0, [0.5, 0.5], f_g, f_x) == pytest.approx(f_x * (1 - (1 - f_g) ** 2))
    # only the full set of legs links: the all-entries formula
    assert model.coupled_risk(lambda p: float(p >= 1.0), [0.5, 0.5], f_g, f_x) == pytest.approx(f_x * f_g**2)
    # one path
    assert model.coupled_risk(lambda p: 0.7, [1.0], f_g, f_x) == pytest.approx(f_x * f_g * 0.7)


def test_power_mean_ratio():
    assert model.power_mean_ratio([1, 1], 1.0) == pytest.approx(1.0)
    assert model.power_mean_ratio([1, 1, 1, 1], 0.5) == pytest.approx(4 ** 0.5)
    assert model.power_mean_ratio([0.8, 0.2], 1.5) == pytest.approx(0.8**1.5 + 0.2**1.5)


def test_predict_uses_the_observed_share_and_orders_policies():
    two_legs = {"extra_paths": [PathSpec("random", 3)], "observed_legs": [0], "suite_bin_widths_s": [0.25],
                "mix_strategy": "exponential", "mix_delay_ms": 50.0, "duration_s": 40.0, "real_rate": 40.0}
    iid = model.predict(_config(split_strategy="iid", split_weights=[0.8, 0.2], **two_legs))
    rr = model.predict(_config(split_strategy="round_robin", **two_legs))
    full = model.predict(_config(**{k: v for k, v in two_legs.items() if k not in ("extra_paths", "observed_legs")}))
    assert iid["model_observed_share"] == pytest.approx(0.8)
    assert iid["model_a1_w0.25_r"] == pytest.approx(math.sqrt(0.8) * full["model_a1_w0.25_r"], rel=0.02)
    assert rr["model_a1_w0.25_r"] > 0.95 * full["model_a1_w0.25_r"]


def test_wave_mode_aligns_session_timestamps():
    config = _config(name="waves", seed=4, duration_s=1.5, grace_period_s=0.8, num_nodes=6, num_sessions=6,
                     max_concurrent_sessions=2, path_length=3, real_rate=10.0, crypto_algorithm="aes256gcm",
                     adversaries=["global_observer"])
    result = run_experiment(config)
    assert result.metrics["delivery_rate"] == 1.0
    assert 0 < result.metrics["oneway_delay_p50_s"] < 0.1


def test_fidelity_check_reports_host_noise():
    config = _config(name="fid", seed=5, duration_s=1.5, grace_period_s=0.8, num_nodes=6, num_sessions=3,
                     path_length=3, real_rate=10.0, crypto_algorithm="aes256gcm")
    report = run_fidelity(config)
    assert report["reference"] == "smallest attacker bin width"
    assert report["limit_s"] == pytest.approx(0.01)
    assert report["host_noise_p95_s"] >= 0
    assert isinstance(report["passes"], bool)


def test_burst_generator_keeps_the_rate_and_is_overdispersed():
    from anontestlab.traffic import get_generator

    gen = get_generator("burst", 40.0, burst_mean_cells=12.0, burst_gap_ms=2.0, unrelated=1)
    times = np.array(gen.emission_times(random.Random(1), 5000.0))
    assert len(times) / 5000.0 == pytest.approx(40.0, rel=0.03)
    assert np.all(np.diff(times) >= 0)
    counts = np.bincount((times / 1.0).astype(int))
    assert counts.var() / counts.mean() == pytest.approx(2 * 12 - 1, rel=0.15)


def test_dispersion_forms_reduce_to_poisson_and_approach_one_for_bursty_counts():
    assert model.policy_factor("iid", 0.5, 2, 10.0, 2.0, 0.25, dispersion=1.0) == pytest.approx(math.sqrt(0.5))
    assert model.policy_factor("iid", 0.5, 2, 10.0, 2.0, 0.25, dispersion=15.0) == pytest.approx(
        1 / math.sqrt(1 + 1 / 15.0))
    assert model.policy_factor("batch", 0.5, 2, 10.0, 5.0, 0.25, dispersion=20.0) == pytest.approx(
        math.sqrt(0.5 / (1 + 0.5 * 10.0 / 20.0)))


def test_predict_uses_the_measured_dispersion_of_the_generator():
    base = {"name": "t", "duration_s": 40.0, "real_rate": 40.0, "mix_strategy": "exponential",
            "mix_delay_ms": 25.0, "split_strategy": "iid", "observed_legs": [0], "suite_bin_widths_s": [0.25],
            "suite_lag_max_s": 1.0, "extra_paths": [PathSpec("random", 3)]}
    poisson = model.predict(ExperimentConfig(**base))
    burst = model.predict(ExperimentConfig(real_traffic_distribution="burst", burst_mean_cells=12.0, **base))
    assert poisson["model_dispersion_w0.25"] == 1.0
    assert burst["model_dispersion_w0.25"] > 15.0
    assert burst["model_a1_w0.25_r"] > poisson["model_a1_w0.25_r"] + 0.2
