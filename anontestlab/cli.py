from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .experiment import ExperimentConfig, compare_experiments, run_experiment, run_sweep
from .wizard import run_wizard


def _print_metrics(title: str, metrics: dict[str, float]) -> None:
    print(f"\nResults for {title}")
    print("─" * 40)
    for k, v in metrics.items():
        v_str = f"{v:.4f}" if isinstance(v, float) else str(v)
        print(f"{k:30s} {v_str}")


def _parse_value(raw: str):
    for caster in (int, float):
        try:
            return caster(raw)
        except ValueError:
            continue
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atl")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run an experiment from a YAML spec")
    run_p.add_argument("experiment_yaml", type=str)
    run_p.add_argument("--out", type=str, default=None)

    compare_p = sub.add_parser("compare", help="Run two experiments and diff their metrics")
    compare_p.add_argument("experiment_yaml_a", type=str)
    compare_p.add_argument("experiment_yaml_b", type=str)
    compare_p.add_argument("--out", type=str, default=None)

    sweep_p = sub.add_parser("sweep", help="Run one experiment repeatedly, varying one parameter")
    sweep_p.add_argument("experiment_yaml", type=str)
    sweep_p.add_argument("--param", type=str, required=True)
    sweep_p.add_argument("--values", type=str, required=True, help="Comma-separated values")
    sweep_p.add_argument("--out", type=str, default=None)

    sub.add_parser("wizard", help="Interactively build and run an experiment")

    dashboard_p = sub.add_parser("dashboard", help="Launch the local web dashboard")
    dashboard_p.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)

    if args.command == "run":
        config = ExperimentConfig.from_yaml(args.experiment_yaml)
        out_dir = Path(args.out) if args.out else Path("results") / config.name
        result = run_experiment(config, out_dir=out_dir)
        _print_metrics(config.name, result.metrics)
        if result.baseline_result is not None:
            print(f"\nBaseline comparison ({result.baseline_result.config.name})")
            print("─" * 40)
            for k in sorted(set(result.metrics) | set(result.baseline_result.metrics)):
                b, t = result.baseline_result.metrics.get(k), result.metrics.get(k)
                b_s = f"{b:.4f}" if isinstance(b, float) else str(b)
                t_s = f"{t:.4f}" if isinstance(t, float) else str(t)
                print(f"{k:28s} {b_s:>12s} {t_s:>12s}")
        print(f"\nWritten to {out_dir}/")
        return 0

    if args.command == "compare":
        config_a = ExperimentConfig.from_yaml(args.experiment_yaml_a)
        config_b = ExperimentConfig.from_yaml(args.experiment_yaml_b)
        out_dir = Path(args.out) if args.out else Path("results") / f"{config_a.name}_vs_{config_b.name}"
        comparison = compare_experiments(config_a, config_b, out_dir=out_dir)
        print(f"\n{config_a.name} vs {config_b.name}")
        print("─" * 60)
        for k, a, b, d in comparison.rows():
            a_s = f"{a:.4f}" if isinstance(a, float) else str(a)
            b_s = f"{b:.4f}" if isinstance(b, float) else str(b)
            d_s = f"{d:+.4f}" if isinstance(d, float) else ""
            print(f"{k:28s} {a_s:>12s} {b_s:>12s} {d_s:>10s}")
        print(f"\nWritten to {out_dir}/")
        return 0

    if args.command == "sweep":
        base_config = ExperimentConfig.from_yaml(args.experiment_yaml)
        values = [_parse_value(v.strip()) for v in args.values.split(",")]
        out_dir = Path(args.out) if args.out else Path("results") / f"{base_config.name}_sweep_{args.param}"
        sweep = run_sweep(base_config, args.param, values, out_dir=out_dir)
        print(f"\nSweep of {base_config.name} over {args.param}")
        print("─" * 40)
        for row in sweep.rows:
            print(row)
        print(f"\nWritten to {out_dir}/")
        return 0

    if args.command == "wizard":
        config = run_wizard()
        out_dir = Path("results") / config.name
        result = run_experiment(config, out_dir=out_dir)
        _print_metrics(config.name, result.metrics)
        print(f"\nWritten to {out_dir}/")
        return 0

    if args.command == "dashboard":
        try:
            from .dashboard.server import main as dashboard_main
        except ImportError:
            print("The dashboard needs extra dependencies: pip install -e '.[dashboard]'")
            return 1
        dashboard_main(["--port", str(args.port)])
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
