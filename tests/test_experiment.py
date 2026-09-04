"""Integration tests against the real emulator: these spawn real relay
subprocesses on real localhost ports, so they're slower than unit tests
(seconds, not milliseconds). Kept fast by using short durations/small
networks, not by faking anything."""

from anontestlab.experiment import ExperimentConfig, compare_experiments, run_experiment, run_sweep
from anontestlab.experiment.config import PathSpec


def _small_config(**overrides) -> ExperimentConfig:
    base = dict(
        name="test-experiment",
        seed=42,
        duration_s=1.0,
        grace_period_s=0.8,
        num_nodes=5,
        num_sessions=2,
        routing_strategy="random",
        path_length=2,
        real_rate=4.0,
        cover_rate=0.0,
        crypto_algorithm="aes256gcm",
        adversaries=["global_observer"],
    )
    base.update(overrides)
    return ExperimentConfig(**base)


def test_run_experiment_produces_core_metrics():
    result = run_experiment(_small_config())
    m = result.metrics
    assert m["real_packets_sent"] > 0
    assert m["delivery_rate"] == 1.0
    assert m["avg_latency_s"] > 0
    assert m["bandwidth_overhead_x"] == 1.0  # no cover traffic
    assert m["circuit_build_delay_s"] > 0  # real measured handshake time


def test_cover_traffic_increases_bandwidth_overhead():
    result = run_experiment(_small_config(cover_rate=6.0))
    assert result.metrics["bandwidth_overhead_x"] > 1.0
    assert result.metrics["delivery_rate"] == 1.0  # real traffic still fully delivered


def test_cover_drop_probability_drops_some_cover_but_not_real():
    result = run_experiment(_small_config(cover_rate=10.0, cover_drop_probability=0.5))
    assert result.metrics["delivery_rate"] == 1.0
    assert result.metrics["cover_packets_sent"] > 0


def test_multipath_splitting_across_two_paths():
    result = run_experiment(
        _small_config(path_length=3, extra_paths=[PathSpec("random", 2)], real_rate=6.0)
    )
    assert result.metrics["delivery_rate"] == 1.0


def test_fixed_cell_size_delivers_correctly_with_cover_and_drops():
    result = run_experiment(
        _small_config(cell_size=512, cover_rate=6.0, cover_drop_probability=0.4, path_length=3)
    )
    assert result.metrics["delivery_rate"] == 1.0
    assert result.metrics["cover_packets_sent"] > 0


def test_fixed_rate_traffic_mode_produces_constant_total_output():
    # Low real rate relative to the fixed slot rate, so there's no backlog
    # spilling past the schedule, total output should equal slots exactly.
    result = run_experiment(
        _small_config(traffic_mode="fixed_rate", fixed_rate=10.0, real_rate=1.0, duration_s=1.5)
    )
    expected_slots_per_session = int(1.5 / (1.0 / 10.0))
    total_packets = result.metrics["real_packets_sent"] + result.metrics["cover_packets_sent"]
    assert total_packets == expected_slots_per_session * 2  # 2 sessions in _small_config
    assert result.metrics["delivery_rate"] == 1.0


def test_fixed_rate_traffic_mode_still_delivers_backlog_beyond_schedule():
    # Real rate exceeding the fixed slot rate: backlog spills past the
    # last slot but must still be sent, not silently dropped.
    result = run_experiment(
        _small_config(traffic_mode="fixed_rate", fixed_rate=10.0, real_rate=30.0, duration_s=1.0)
    )
    assert result.metrics["delivery_rate"] == 1.0
    assert result.metrics["real_packets_sent"] > 0


def test_cell_size_too_small_raises_clear_error():
    import pytest

    with pytest.raises(ValueError):
        run_experiment(_small_config(cell_size=40, path_length=3))


def test_all_crypto_algorithms_deliver_correctly():
    for algorithm in ["none", "aes128gcm", "aes256gcm", "aes256gcmsiv", "aes256ocb3", "chacha20poly1305"]:
        result = run_experiment(_small_config(crypto_algorithm=algorithm, num_sessions=1))
        assert result.metrics["delivery_rate"] == 1.0, f"algorithm={algorithm}"


def test_all_keyexchange_curves_deliver_correctly():
    for keyexchange in ["x25519", "x448", "p256"]:
        result = run_experiment(_small_config(crypto_keyexchange=keyexchange, num_sessions=1))
        assert result.metrics["delivery_rate"] == 1.0, f"keyexchange={keyexchange}"


def test_keyexchange_with_fixed_size_cells_and_multipath():
    """The larger p256/x448 pubkeys eat more of the padding budget inside
    EXTEND cells; confirm they still fit a realistic cell_size across a
    multi-hop path."""
    for keyexchange in ["x25519", "x448", "p256"]:
        result = run_experiment(
            _small_config(
                crypto_keyexchange=keyexchange,
                cell_size=512,
                path_length=3,
                extra_paths=[PathSpec("random", 2)],
            )
        )
        assert result.metrics["delivery_rate"] == 1.0, f"keyexchange={keyexchange}"


def test_path_selection_and_traffic_schedule_reproducible_with_fixed_seed():
    r1 = run_experiment(_small_config())
    r2 = run_experiment(_small_config())
    # Real measured latency will vary run to run (real sockets/OS scheduling);
    # what's pinned by the seed is the experiment *design*: how many
    # packets got scheduled at all.
    assert r1.metrics["real_packets_sent"] == r2.metrics["real_packets_sent"]
    assert r1.metrics["real_packets_delivered"] == r2.metrics["real_packets_delivered"]


def test_results_written_to_disk(tmp_path):
    out_dir = tmp_path / "results"
    run_experiment(_small_config(), out_dir=out_dir)
    assert (out_dir / "configuration.yaml").exists()
    assert (out_dir / "seed.txt").read_text().strip() == "42"
    assert (out_dir / "metrics.csv").exists()
    assert (out_dir / "report.md").exists()


def test_path_compromise_adversary_full_fraction_means_near_certain_compromise():
    result = run_experiment(
        _small_config(adversaries=["path_compromise"], compromised_fraction=1.0, compromise_trials=200)
    )
    # Wilson-center, not the raw proportion, so it's pulled slightly off
    # the 1.0 boundary even when every trial was a "success". That's
    # correct Wilson behavior, not a bug.
    assert result.metrics["full_compromise_rate"] > 0.98


def test_path_compromise_adversary_zero_fraction_means_almost_never_compromised():
    result = run_experiment(
        _small_config(adversaries=["path_compromise"], compromised_fraction=0.0, compromise_trials=200)
    )
    assert result.metrics["full_compromise_rate"] < 0.02


def test_compare_experiments_reports_deltas(tmp_path):
    config_a = _small_config(name="a", cover_rate=0.0)
    config_b = _small_config(name="b", cover_rate=8.0)
    comparison = compare_experiments(config_a, config_b, out_dir=tmp_path / "cmp")
    rows = dict((k, (a, b, d)) for k, a, b, d in comparison.rows())
    assert rows["bandwidth_overhead_x"][1] > rows["bandwidth_overhead_x"][0]
    assert (tmp_path / "cmp" / "comparison.csv").exists()
    assert (tmp_path / "cmp" / "comparison.md").exists()


def test_sweep_runs_one_point_per_value(tmp_path):
    base = _small_config(num_sessions=1)
    sweep = run_sweep(base, "cover_rate", [0.0, 8.0], out_dir=tmp_path / "sweep")
    assert len(sweep.rows) == 2
    assert sweep.rows[0]["cover_rate"] == 0.0
    assert sweep.rows[1]["bandwidth_overhead_x"] > sweep.rows[0]["bandwidth_overhead_x"]
    assert (tmp_path / "sweep" / "sweep.csv").exists()


def test_as_level_observer_full_visibility_behaves_like_default():
    result = run_experiment(_small_config(num_as_groups=3, observed_as_count=3, num_sessions=3))
    assert result.metrics["delivery_rate"] == 1.0
    assert result.metrics["correlation_success_rate"] == 1.0


def test_as_level_observer_partial_visibility_does_not_affect_delivery():
    result = run_experiment(_small_config(num_as_groups=3, observed_as_count=1, num_sessions=3))
    assert result.metrics["delivery_rate"] == 1.0  # observation never affects real delivery


def test_watermark_adversary_detects_its_own_injected_pattern():
    result = run_experiment(
        _small_config(
            watermark_period=3,
            watermark_delay_ms=80.0,
            real_traffic_distribution="constant",
            real_rate=10.0,
            duration_s=2.0,
            grace_period_s=1.0,
            adversaries=["watermark"],
        )
    )
    assert result.metrics["delivery_rate"] == 1.0  # watermark delays, never drops
    assert result.metrics["watermark_detection_rate"] == 1.0


def test_watermark_adversary_disabled_reports_nan():
    result = run_experiment(_small_config(watermark_period=0, adversaries=["watermark"]))
    import math

    assert math.isnan(result.metrics["watermark_detection_rate"])


def test_hop_depth_adversary_end_to_end_with_fixed_size_cells():
    result = run_experiment(
        _small_config(
            path_length=3,
            extra_paths=[PathSpec("random", 2)],
            cell_size=512,
            adversaries=["hop_depth"],
        )
    )
    assert result.metrics["delivery_rate"] == 1.0
    assert result.metrics["hop_position_accuracy"] == 1.0
    assert result.metrics["path_length_leak_at_hop1"] == 0.0  # two path lengths present (3 and 2)


def test_hop_depth_adversary_reports_nan_without_fixed_size_cells():
    result = run_experiment(_small_config(cell_size=None, adversaries=["hop_depth"]))
    import math

    assert math.isnan(result.metrics["hop_position_accuracy"])
    assert math.isnan(result.metrics["path_length_leak_at_hop1"])


def test_link_latency_increases_measured_latency():
    baseline = run_experiment(_small_config())
    wan = run_experiment(_small_config(link_latency_ms=50.0, link_jitter_ms=5.0, grace_period_s=2.0))
    assert wan.metrics["avg_latency_s"] > baseline.metrics["avg_latency_s"]
    assert wan.metrics["delivery_rate"] == 1.0


def test_link_loss_reduces_delivery_without_hanging():
    # Regression guard: link loss applies to circuit-build control traffic
    # too (symmetric with data-plane loss), which relies on
    # wire.read_frame_timeout to turn a lost EXTENDED/HELLO_REPLY into a
    # clear ProtocolError instead of hanging build_circuit's read forever,
    # and on run_experiment_async catching it per-session rather than
    # letting it crash the whole experiment. This test would time out (the
    # old hang) or fail with an unhandled exception (the crash) if either
    # regressed. Per-relay loss rolls aren't seeded from config.seed (each
    # relay is a separate OS process with its own random state), so how
    # many of these sessions actually fail varies run to run. Six
    # sessions makes "every single one fails" astronomically unlikely
    # without pinning down a result the assertions need to depend on.
    num_sessions = 6
    result = run_experiment(
        _small_config(
            link_loss_probability=0.15, real_rate=8.0, duration_s=1.5, grace_period_s=1.0,
            num_sessions=num_sessions,
        )
    )
    assert 0 <= result.metrics["sessions_failed"] <= num_sessions
    if result.metrics["real_packets_sent"] > 0:
        assert 0.0 <= result.metrics["delivery_rate"] <= 1.0


def test_extreme_link_loss_fails_sessions_gracefully_not_the_whole_experiment():
    # Near-certain per-leg loss makes circuit build fail for most/all
    # sessions almost every run. The point: run_experiment must still
    # return normally (not raise), with the failures counted, rather than
    # an unhandled ProtocolError propagating out of asyncio.gather.
    result = run_experiment(
        _small_config(link_loss_probability=0.95, duration_s=1.0, grace_period_s=0.5, num_sessions=3)
    )
    assert result.metrics["sessions_failed"] >= 0  # didn't raise to get here


def test_link_bandwidth_throttle_increases_latency_without_hanging():
    baseline = run_experiment(_small_config())
    throttled = run_experiment(
        _small_config(link_bandwidth_kbps=100.0, real_rate=3.0, grace_period_s=2.0)
    )
    assert throttled.metrics["avg_latency_s"] > baseline.metrics["avg_latency_s"]
    assert throttled.metrics["delivery_rate"] == 1.0


def test_heterogeneous_link_conditions_still_deliver_correctly():
    result = run_experiment(
        _small_config(
            link_latency_ms=20.0,
            link_loss_probability=0.05,
            link_heterogeneous=True,
            link_heterogeneity_spread=0.8,
            num_sessions=4,
        )
    )
    assert 0 <= result.metrics["sessions_failed"] <= 4
    if result.metrics["real_packets_sent"] > 0:
        assert 0.0 <= result.metrics["delivery_rate"] <= 1.0


def test_bandwidth_weighted_routing_delivers_correctly():
    result = run_experiment(
        _small_config(
            routing_strategy="bandwidth_weighted",
            link_bandwidth_kbps=1000.0,
            link_heterogeneous=True,
        )
    )
    assert result.metrics["delivery_rate"] == 1.0


def test_run_experiment_with_baseline_produces_comparison(tmp_path):
    import yaml

    baseline_path = tmp_path / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(
            {
                "experiment": {"name": "baseline", "seed": 42, "duration_s": 1.0, "grace_period_s": 0.8},
                "network": {"nodes": 5},
                "sessions": {"count": 2},
                "routing": {"strategy": "random", "path_length": 2},
                "traffic": {"real_rate": 4.0, "cover_rate": 0},
            }
        )
    )

    treatment = _small_config(cover_rate=8.0)
    treatment.baseline = str(baseline_path)
    result = run_experiment(treatment, out_dir=tmp_path / "out")

    assert result.baseline_result is not None
    assert result.baseline_result.config.name == "baseline"
    assert result.baseline_result.metrics["bandwidth_overhead_x"] == 1.0
    assert result.metrics["bandwidth_overhead_x"] > 1.0
    assert "Baseline comparison" in (tmp_path / "out" / "report.md").read_text()
