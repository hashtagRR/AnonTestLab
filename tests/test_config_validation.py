"""Fast pure-Python tests for ExperimentConfig.validate(), no
subprocesses/sockets needed."""
import pytest

from anontestlab.experiment.config import ExperimentConfig, PathSpec


def _config(**overrides) -> ExperimentConfig:
    base = dict(name="t")
    base.update(overrides)
    return ExperimentConfig(**base)


def test_default_config_is_valid():
    _config().validate()  # must not raise


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_s": 0},
        {"duration_s": -1},
        {"num_nodes": 0},
        {"num_nodes": 255},
        {"num_sessions": 0},
        {"real_rate": -1},
        {"cover_rate": -1},
        {"cover_drop_probability": 1.5},
        {"cover_drop_probability": -0.1},
        {"traffic_mode": "bogus"},
        {"traffic_mode": "fixed_rate", "fixed_rate": 0},
        {"cell_size": 0},
        {"cell_size": -10},
        {"crypto_algorithm": "rot13"},
        {"split_strategy": "bogus"},
        {"path_length": 0},
        {"path_length": 999},  # exceeds default num_nodes
        {"num_as_groups": 0},
        {"observed_path_count": 0},
        {"observed_as_count": -1},
        {"compromised_fraction": 1.5},
        {"compromised_fraction": -0.1},
        {"compromise_trials": -1},
        {"watermark_period": -1},
        {"link_latency_ms": -1},
        {"link_jitter_ms": -1},
        {"link_loss_probability": 1.5},
        {"link_bandwidth_kbps": 0},
        {"link_heterogeneity_spread": 1.0},
        {"link_heterogeneity_spread": -0.1},
        {"routing_strategy": "bogus"},
    ],
)
def test_invalid_values_are_rejected(overrides):
    with pytest.raises(ValueError):
        _config(**overrides).validate()


def test_extra_path_length_exceeding_nodes_is_rejected():
    with pytest.raises(ValueError):
        _config(num_nodes=3, extra_paths=[PathSpec("random", 10)]).validate()


def test_error_message_lists_all_problems_at_once():
    with pytest.raises(ValueError) as exc_info:
        _config(num_nodes=0, num_sessions=0, real_rate=-1).validate()
    message = str(exc_info.value)
    assert "num_nodes" in message
    assert "num_sessions" in message
    assert "real_rate" in message


def test_from_yaml_runs_validation(tmp_path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "experiment:\n  name: bad\n  duration_s: 1.0\n"
        "traffic_shaping:\n  enabled: true\n  mode: fixed_rate\n  rate: 0\n"
    )
    with pytest.raises(ValueError):
        ExperimentConfig.from_yaml(bad_yaml)
