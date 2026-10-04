"""Paired multi-seed comparison: run a reference and a treatment config
under the same list of seeds, pair the runs by seed, and classify the
difference in one metric with a paired bootstrap plus an explicit
equivalence margin (see metrics.stats.paired_bootstrap_delta). One run
per config is a single draw; this is the check that a difference is
bigger than seed-to-seed variation before anyone reads it as a result."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from ..metrics.stats import PairedEffect, paired_bootstrap_delta
from .config import ExperimentConfig
from .runner import run_experiment


@dataclass
class PairedResult:
    metric: str
    seeds: list[int]
    reference_name: str
    treatment_name: str
    reference_values: list[float]
    treatment_values: list[float]
    effect: PairedEffect
    margin: float


def run_paired(
    reference: ExperimentConfig,
    treatment: ExperimentConfig,
    seeds: list[int],
    metric: str = "tpr_at_fpr_0.001",
    margin: float = 0.05,
    resamples: int = 10000,
    bootstrap_seed: int = 0,
    out_dir: Path | None = None,
) -> PairedResult:
    ref_values, treat_values = [], []
    for seed in seeds:
        for base, sink in ((reference, ref_values), (treatment, treat_values)):
            metrics = run_experiment(dataclasses.replace(base, seed=seed)).metrics
            if metric not in metrics:
                raise ValueError(f"metric {metric!r} not produced by {base.name!r}; available: {sorted(metrics)}")
            sink.append(float(metrics[metric]))
    effect = paired_bootstrap_delta(
        ref_values, treat_values, margin=margin, resamples=resamples, seed=bootstrap_seed
    )
    result = PairedResult(metric, list(seeds), reference.name, treatment.name, ref_values, treat_values, effect, margin)
    if out_dir is not None:
        write_paired(result, out_dir)
    return result


def write_paired(result: PairedResult, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Fixed column names, not the configs' own names: reference and
    # treatment commonly share a name (the same base config, one field
    # changed), and a header of "seed,sweep-base,sweep-base,delta" would
    # give both columns the same dict key once read back - silently
    # losing the reference column to the treatment one wherever this CSV
    # is parsed. reference_name/treatment_name are still carried in
    # paired_summary.json for display.
    lines = ["seed,reference,treatment,delta"]
    for s, r, t in zip(result.seeds, result.reference_values, result.treatment_values):
        lines.append(f"{s},{r},{t},{t - r}")
    (out_dir / "paired_runs.csv").write_text("\n".join(lines) + "\n")
    summary = {
        "metric": result.metric,
        "reference": result.reference_name,
        "treatment": result.treatment_name,
        "margin": result.margin,
        **dataclasses.asdict(result.effect),
    }
    (out_dir / "paired_summary.json").write_text(json.dumps(summary, indent=2))
