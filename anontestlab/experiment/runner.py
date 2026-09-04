from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from ..adversary import get_adversary
from ..emulator.orchestrator import run_experiment as run_emulated_experiment
from .config import ExperimentConfig


@dataclass
class ExperimentResult:
    config: ExperimentConfig
    metrics: dict[str, float]
    baseline_result: "ExperimentResult | None" = None


def run_experiment(config: ExperimentConfig, out_dir: Path | None = None) -> ExperimentResult:
    config.validate()
    collector, ctx, avg_build_delay, sessions_failed = run_emulated_experiment(config)

    metrics = collector.summary()
    metrics["circuit_build_delay_s"] = avg_build_delay
    metrics["sessions_failed"] = sessions_failed

    rng = random.Random(config.seed)
    for adversary_name in config.adversaries:
        adversary = get_adversary(adversary_name, config)
        result = adversary.attack(ctx, rng)
        metrics.update(result.metrics)

    baseline_result = None
    if config.baseline:
        baseline_config = ExperimentConfig.from_yaml(config.baseline)
        baseline_result = run_experiment(baseline_config)  # baseline configs aren't expected to chain

    result = ExperimentResult(config=config, metrics=metrics, baseline_result=baseline_result)
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
