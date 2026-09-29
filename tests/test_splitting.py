"""Split policies (emulator/splitting.py), common-exit path selection and
per-leg observation. The last test runs a two-leg session on real relays."""
import random
from collections import Counter

import pytest

from anontestlab.emulator.orchestrator import select_node_paths
from anontestlab.emulator.splitting import LegScheduler
from anontestlab.experiment import ExperimentConfig, run_experiment
from anontestlab.experiment.config import PathSpec


def _assign_all(scheduler, times, seed=0):
    rng = random.Random(seed)
    return [scheduler.assign(t, rng) for t in times]


def _times(n, rate=40.0, seed=1):
    rng = random.Random(seed)
    t, out = 0.0, []
    for _ in range(n):
        t += rng.expovariate(rate)
        out.append(t)
    return out


def test_round_robin_alternates_and_weighted_round_robin_is_exact():
    assert _assign_all(LegScheduler("round_robin", 2), range(6)) == [0, 1, 0, 1, 0, 1]
    legs = _assign_all(LegScheduler("round_robin", 2, weights=[3, 1]), range(400))
    assert Counter(legs) == {0: 300, 1: 100}
    assert max(len(run) for run in "".join(map(str, legs)).split("1")) <= 3  # spread out, no long runs


def test_iid_matches_the_weights():
    legs = _assign_all(LegScheduler("iid", 2, weights=[0.8, 0.2]), range(20000))
    assert Counter(legs)[0] / len(legs) == pytest.approx(0.8, abs=0.01)


def test_batch_keeps_consecutive_cells_together():
    times = _times(20000)
    legs = _assign_all(LegScheduler("batch", 2, weights=[0.5, 0.5], batch_mean_s=2.0), times)
    switches = sum(1 for a, b in zip(legs, legs[1:]) if a != b)
    duration = times[-1]
    # batches last 2 s on average and half of the draws repeat the leg,
    # so switches happen about once every 4 s
    assert switches == pytest.approx(duration / 4.0, rel=0.25)
    assert Counter(legs)[0] / len(legs) == pytest.approx(0.5, abs=0.1)


def test_latency_policy_prefers_the_fast_leg_and_overflows_under_load():
    light = _assign_all(LegScheduler("latency", 2, leg_rtt_s=[0.05, 0.1], leg_window=8), _times(5000, rate=20))
    heavy = _assign_all(LegScheduler("latency", 2, leg_rtt_s=[0.05, 0.1], leg_window=8), _times(5000, rate=400))
    assert Counter(light)[0] / len(light) > 0.99
    assert 0.2 < Counter(heavy)[1] / len(heavy) < 0.8


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError):
        LegScheduler("bogus", 2)


def _config(**overrides):
    base = {"name": "t", "num_nodes": 12, "path_length": 3, "extra_paths": [PathSpec("random", 3)]}
    base.update(overrides)
    return ExperimentConfig(**base)


def test_common_exit_shares_the_exit_and_nothing_else():
    config = _config(merge="common_exit")
    nodes = [f"n{i}" for i in range(12)]
    for seed in range(50):
        a, b = select_node_paths(config, nodes, random.Random(seed), None)
        assert a[-1] == b[-1]
        assert not set(a[:-1]) & set(b[:-1])
        assert len(set(a)) == len(a) and len(set(b)) == len(b)


def test_multipath_config_validation():
    for bad in (
        {"split_strategy": "bogus"},
        {"split_weights": [1.0]},
        {"split_weights": [0.5, -0.5]},
        {"split_leg_rtt_ms": [50.0]},
        {"split_leg_window": 0},
        {"merge": "somewhere"},
        {"observed_legs": [2]},
        {"egress_observation": "partial"},
        {"merge": "common_exit", "num_nodes": 4},
    ):
        with pytest.raises(ValueError):
            _config(**bad).validate()


def test_common_exit_with_one_observed_leg_on_real_relays():
    config = _config(
        name="conflux-like",
        seed=21,
        duration_s=3.0,
        grace_period_s=1.0,
        num_sessions=3,
        real_rate=20.0,
        crypto_algorithm="aes256gcm",
        split_strategy="round_robin",
        merge="common_exit",
        observed_legs=[0],
        egress_observation="merged",
        adversaries=["global_observer"],
    )
    result = run_experiment(config)
    m = result.metrics
    assert m["delivery_rate"] == 1.0
    assert m["leg_0_real_share"] == pytest.approx(0.5, abs=0.02)
    assert m["leg_1_real_share"] == pytest.approx(0.5, abs=0.02)
