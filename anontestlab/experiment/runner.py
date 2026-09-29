from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..adversary import get_adversary
from ..emulator.orchestrator import run_experiment as run_emulated_experiment
from .config import ExperimentConfig


@dataclass
class ExperimentResult:
    config: ExperimentConfig
    metrics: dict[str, float]
    baseline_result: ExperimentResult | None = None
    artifacts: dict[str, dict] = field(default_factory=dict)  # adversary name -> arrays written as <name>.npz


def run_experiment(
    config: ExperimentConfig,
    out_dir: Path | None = None,
    on_progress: Callable[[dict], None] | None = None,
    _baseline_depth: int = 0,
) -> ExperimentResult:
    config.validate()
    collector, ctx, avg_build_delay, sessions_failed = run_emulated_experiment(config, on_progress)

    metrics = collector.summary()
    if config.num_paths > 1:
        per_leg = [obs.leg_real_counts for obs in ctx.sessions.values() if sum(obs.leg_real_counts) > 0]
        for leg in range(config.num_paths):
            shares = [counts[leg] / sum(counts) for counts in per_leg]
            metrics[f"leg_{leg}_real_share"] = sum(shares) / len(shares) if shares else float("nan")
    metrics["circuit_build_delay_s"] = avg_build_delay
    metrics["sessions_failed"] = sessions_failed

    rng = random.Random(config.seed)
    artifacts: dict[str, dict] = {}
    for adversary_name in config.adversaries:
        adversary = get_adversary(adversary_name, config)
        result = adversary.attack(ctx, rng)
        metrics.update(result.metrics)
        if result.artifacts:
            artifacts[adversary_name] = result.artifacts

    baseline_result = None
    if config.baseline:
        if _baseline_depth >= 1:
            raise ValueError(
                f"baseline chains aren't supported: {config.name!r} was reached as a baseline "
                f"and itself sets baseline: {config.baseline!r}. Point a baseline directly at a "
                "config that has no baseline of its own."
            )
        baseline_config = ExperimentConfig.from_yaml(config.baseline)
        baseline_result = run_experiment(baseline_config, _baseline_depth=_baseline_depth + 1)

    result = ExperimentResult(config=config, metrics=metrics, baseline_result=baseline_result, artifacts=artifacts)
    if out_dir is not None:
        write_results(result, out_dir)
    return result


def write_results(result: ExperimentResult, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "configuration.yaml").write_text(_to_yaml(result.config.to_dict()))
    (out_dir / "seed.txt").write_text(str(result.config.seed) + "\n")
    (out_dir / "metrics.json").write_text(json.dumps(result.metrics, indent=2, default=str))

    with (out_dir / "metrics.csv").open("w") as f:
        f.write("metric,value\n")
        for k, v in result.metrics.items():
            f.write(f"{k},{v}\n")

    (out_dir / "report.md").write_text(_report_md(result))

    for name, arrays in result.artifacts.items():
        np.savez_compressed(out_dir / f"{name}.npz", **arrays)


def _to_yaml(d: dict) -> str:
    import yaml

    return yaml.safe_dump(d, sort_keys=False)


def _fmt(x: object) -> str:
    if isinstance(x, float):
        return f"{x:.4f}"
    return "" if x is None else str(x)


def _baseline_delta_rows(treatment: dict, baseline: dict) -> list[tuple[str, object, object, object]]:
    rows = []
    for k in sorted(set(treatment) | set(baseline)):
        b, t = baseline.get(k), treatment.get(k)
        delta = t - b if isinstance(b, (int, float)) and isinstance(t, (int, float)) else None
        rows.append((k, b, t, delta))
    return rows


def _report_md(result: ExperimentResult) -> str:
    lines = [f"# {result.config.name}", "", "## Configuration", "", "```yaml"]
    lines.append(_to_yaml(result.config.to_dict()).rstrip())
    lines += ["```", "", "## Results", "", "| metric | value |", "|---|---|"]
    for k, v in result.metrics.items():
        lines.append(f"| {k} | {_fmt(v)} |")

    if result.baseline_result is not None:
        lines += [
            "",
            f"## Baseline comparison ({result.baseline_result.config.name})",
            "",
            "| metric | baseline | treatment | delta |",
            "|---|---|---|---|",
        ]
        for k, b, t, d in _baseline_delta_rows(result.metrics, result.baseline_result.metrics):
            lines.append(f"| {k} | {_fmt(b)} | {_fmt(t)} | {_fmt(d)} |")

    return "\n".join(lines) + "\n"
