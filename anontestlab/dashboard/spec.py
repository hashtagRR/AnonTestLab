"""Conversions between ExperimentConfig and the nested YAML spec format.

ExperimentConfig.from_yaml reads the nested spec (experiment:, network:,
routing:, ...), but write_results stores configuration.yaml as the flat
dataclass dict, which from_yaml can't read back. The dashboard edits the
flat dict (one key per config field) and needs a runnable spec from it, so
config_to_spec is the inverse of from_yaml and config_from_flat the
inverse of to_dict. tests/test_dashboard.py round-trips every example
through both.
"""
from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Any

import yaml

from ..experiment import ExperimentConfig
from ..experiment.config import PathSpec

_FIELDS = {f.name for f in dataclasses.fields(ExperimentConfig)}


def config_from_flat(flat: dict[str, Any]) -> ExperimentConfig:
    """Builds a config from the flat dict that to_dict() (and so
    configuration.yaml) produces. Unknown keys are an error, not ignored, so
    a typo in a hand-edited field doesn't silently fall back to a default."""
    unknown = set(flat) - _FIELDS
    if unknown:
        raise ValueError(f"unknown config fields: {sorted(unknown)}")
    values = dict(flat)
    values["extra_paths"] = [
        p if isinstance(p, PathSpec) else PathSpec(**p) for p in values.get("extra_paths") or []
    ]
    return ExperimentConfig(**values)


def config_to_spec(c: ExperimentConfig) -> dict[str, Any]:
    """The nested spec that ExperimentConfig.from_yaml turns back into `c`."""
    spec: dict[str, Any] = {
        "experiment": {
            "name": c.name,
            "mode": c.mode,
            "seed": c.seed,
            "duration_s": c.duration_s,
            "grace_period_s": c.grace_period_s,
        },
        "network": {"nodes": c.num_nodes, "as_groups": c.num_as_groups},
        "sessions": {"count": c.num_sessions},
    }
    if c.max_concurrent_sessions is not None:
        spec["sessions"]["max_concurrent"] = c.max_concurrent_sessions
    if c.baseline is not None:
        spec["baseline"] = c.baseline

    routing: dict[str, Any]
    if c.extra_paths:
        routing = {"paths": [{"strategy": p.strategy, "path_length": p.path_length} for p in c.paths]}
    else:
        routing = {"strategy": c.routing_strategy, "path_length": c.path_length}
    routing.update(
        split_strategy=c.split_strategy,
        split_batch_mean_s=c.split_batch_mean_s,
        split_leg_window=c.split_leg_window,
        merge=c.merge,
    )
    if c.split_weights is not None:
        routing["split_weights"] = list(c.split_weights)
    if c.split_leg_rtt_ms is not None:
        routing["split_leg_rtt_ms"] = list(c.split_leg_rtt_ms)
    spec["routing"] = routing

    spec["traffic"] = {
        "distribution": c.real_traffic_distribution,
        "real_rate": c.real_rate,
        "burst_mean_cells": c.burst_mean_cells,
        "burst_gap_ms": c.burst_gap_ms,
        "cover_distribution": c.cover_traffic_distribution,
        "cover_rate": c.cover_rate,
    }
    spec["cover_behaviour"] = {"drop_probability": c.cover_drop_probability, "drop_mode": c.cover_drop_mode}
    spec["mixing"] = {
        "strategy": c.mix_strategy,
        "delay_ms": c.mix_delay_ms,
        "pool_interval_ms": c.pool_interval_ms,
        "release_probability": c.pool_release_probability,
        "interval_jitter": c.pool_interval_jitter,
    }
    spec["crypto"] = {"algorithm": c.crypto_algorithm, "keyexchange": c.crypto_keyexchange}
    spec["traffic_shaping"] = {
        "enabled": c.cell_size is not None,
        "mode": c.traffic_mode,
        "rate": c.fixed_rate,
    }
    if c.cell_size is not None:
        spec["traffic_shaping"]["cell_size"] = c.cell_size

    link: dict[str, Any] = {
        "latency_ms": c.link_latency_ms,
        "jitter_ms": c.link_jitter_ms,
        "loss_probability": c.link_loss_probability,
        "heterogeneous": c.link_heterogeneous,
        "heterogeneity_spread": c.link_heterogeneity_spread,
        "per_edge": c.link_per_edge,
    }
    if c.link_bandwidth_kbps is not None:
        link["bandwidth_kbps"] = c.link_bandwidth_kbps
    spec["link_conditions"] = link

    adversary: dict[str, Any] = {
        "types": list(c.adversaries),
        "observed_paths": "all" if c.observed_path_count is None else c.observed_path_count,
        "egress_observation": c.egress_observation,
        "observed_as": "all" if c.observed_as_count is None else c.observed_as_count,
        "compromised_fraction": c.compromised_fraction,
        "compromise_trials": c.compromise_trials,
        "observation": {"bin_width_ms": c.observer_bin_width_ms},
        "classifier": {"type": c.observer_classifier, "threshold": c.observer_threshold},
        "watermark": {"period": c.watermark_period, "delay_ms": c.watermark_delay_ms},
        "evaluation": {"calibration_fraction": c.observer_calibration_fraction},
        "correlation_suite": {
            "attackers": list(c.suite_attackers),
            "bin_widths_s": list(c.suite_bin_widths_s),
            "psi": list(c.suite_psi),
            "base_rates": list(c.suite_base_rates),
            "fpr_targets": list(c.suite_fpr_targets),
            "window_quantiles": list(c.suite_window_quantiles),
            "latency_floor_ms": c.suite_latency_floor_ms,
            "lr_step_ms": c.suite_lr_step_ms,
        },
    }
    if c.observed_legs is not None:
        adversary["observed_legs"] = list(c.observed_legs)
    if c.suite_lag_max_s is not None:
        adversary["correlation_suite"]["lag_max_s"] = c.suite_lag_max_s
    spec["adversary"] = adversary
    return spec


def spec_yaml(c: ExperimentConfig) -> str:
    return yaml.safe_dump(config_to_spec(c), sort_keys=False)


def validated(c: ExperimentConfig) -> tuple[list[str], list[str]]:
    """Runs config.validate() and returns (errors, warnings) instead of
    raising, so the builder can show both while the user is still editing."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            c.validate()
            errors: list[str] = []
        except ValueError as e:
            errors = [line.strip()[2:] for line in str(e).splitlines()[1:]] or [str(e)]
    return errors, [str(w.message) for w in caught]


def load_spec_text(yaml_text: str, base_dir: Path | None = None) -> ExperimentConfig:
    """from_yaml for text instead of a path. A relative `baseline:` resolves
    against base_dir (the server's working directory by default) rather than
    against wherever the temporary file happened to land."""
    import tempfile

    base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir=base_dir, delete=False) as f:
        f.write(yaml_text)
        tmp_path = Path(f.name)
    try:
        return ExperimentConfig.from_yaml(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
