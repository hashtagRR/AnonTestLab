from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from .config import ExperimentConfig
from .runner import run_experiment


@dataclass
class SweepResult:
    param: str
    rows: list[dict[str, object]]  # each row: {param: value, **metrics}


def run_sweep(
    base_config: ExperimentConfig, param: str, values: list, out_dir: Path | None = None
) -> SweepResult:
    if not hasattr(base_config, param):
        raise ValueError(f"unknown sweep parameter '{param}'")

    rows = []
    for value in values:
        config = dataclasses.replace(base_config, **{param: value})
        result = run_experiment(config)
        rows.append({param: value, **result.metrics})

    sweep = SweepResult(param=param, rows=rows)
    if out_dir is not None:
        write_sweep(sweep, out_dir)
    return sweep


def write_sweep(sweep: SweepResult, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not sweep.rows:
        return
    fieldnames = list(sweep.rows[0].keys())
    lines = [",".join(fieldnames)]
    for row in sweep.rows:
        lines.append(",".join(str(row.get(f, "")) for f in fieldnames))
    (out_dir / "sweep.csv").write_text("\n".join(lines) + "\n")
