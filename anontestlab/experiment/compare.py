from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import ExperimentConfig
from .runner import run_experiment


@dataclass
class ComparisonResult:
    config_a: ExperimentConfig
    config_b: ExperimentConfig
    metrics_a: dict[str, float]
    metrics_b: dict[str, float]

    def rows(self) -> list[tuple[str, object, object, object]]:
        keys = sorted(set(self.metrics_a) | set(self.metrics_b))
        rows = []
        for k in keys:
            a = self.metrics_a.get(k)
            b = self.metrics_b.get(k)
            delta = b - a if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
            rows.append((k, a, b, delta))
        return rows


def compare_experiments(
    config_a: ExperimentConfig, config_b: ExperimentConfig, out_dir: Path | None = None
) -> ComparisonResult:
    result_a = run_experiment(config_a)
    result_b = run_experiment(config_b)
    comparison = ComparisonResult(config_a, config_b, result_a.metrics, result_b.metrics)
    if out_dir is not None:
        write_comparison(comparison, out_dir)
    return comparison


def _fmt(x: object) -> str:
    if isinstance(x, float):
        return f"{x:.4f}"
    return "" if x is None else str(x)


def write_comparison(comparison: ComparisonResult, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_lines = ["metric,a,b,delta"]
    for k, a, b, d in comparison.rows():
        csv_lines.append(f"{k},{_fmt(a)},{_fmt(b)},{_fmt(d)}")
    (out_dir / "comparison.csv").write_text("\n".join(csv_lines) + "\n")

    md_lines = [
        f"# {comparison.config_a.name} vs {comparison.config_b.name}",
        "",
        f"| metric | {comparison.config_a.name} | {comparison.config_b.name} | delta |",
        "|---|---|---|---|",
    ]
    for k, a, b, d in comparison.rows():
        md_lines.append(f"| {k} | {_fmt(a)} | {_fmt(b)} | {_fmt(d)} |")
    (out_dir / "comparison.md").write_text("\n".join(md_lines) + "\n")
