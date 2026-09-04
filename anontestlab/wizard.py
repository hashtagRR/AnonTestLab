"""Interactive CLI wizard: `anontestlab wizard`. Stdlib `input()` only, no
extra dependency. Walks through mode selection then, for custom mode,
the parameter set scoped for v0.1 (nodes, paths/splitting, cover traffic,
crypto algorithm, adversaries)."""
from __future__ import annotations

from .experiment.config import ExperimentConfig, PathSpec


def _prompt(msg: str, default) -> str:
    raw = input(f"{msg} [{default}]: ").strip()
    return raw if raw else str(default)


def _prompt_bool(msg: str, default: bool) -> bool:
    d = "y" if default else "n"
    raw = input(f"{msg} [y/n] [{d}]: ").strip().lower()
    return raw.startswith("y") if raw else default


def _prompt_choice(msg: str, choices: list[str], default: str) -> str:
    raw = input(f"{msg} ({'/'.join(choices)}) [{default}]: ").strip().lower()
    return raw if raw in choices else default


def run_wizard() -> ExperimentConfig:
    print("AnonTestLab experiment wizard")
    print("=" * 40)

    mode = _prompt_choice("Mode", ["tor_like", "custom"], "tor_like")
    name = _prompt("Experiment name", "wizard-run")
    seed = int(_prompt("Seed", 20260903))
    duration_s = float(_prompt("Duration (s)", 10))
    num_sessions = int(_prompt("Number of sessions", 5))
    num_nodes = int(_prompt("Number of relay nodes", 10))

    if mode == "tor_like":
        print("\nTor-like preset: 1 path, 3 hops, random relay selection, no cover, no splitting.")
        return ExperimentConfig.tor_like(
            name, seed=seed, duration_s=duration_s, num_sessions=num_sessions, num_nodes=num_nodes
        )

    path_length = int(_prompt("Path length (hops per path)", 3))
    num_paths = int(_prompt("Number of paths (traffic split across them)", 1))
    extra_paths: list[PathSpec] = []
    split_strategy = "round_robin"
    if num_paths > 1:
        if _prompt_bool("Use the same path length for every path?", True):
            extra_paths = [PathSpec("random", path_length) for _ in range(num_paths - 1)]
        else:
            for i in range(2, num_paths + 1):
                pl = int(_prompt(f"Path {i} length", path_length))
                extra_paths.append(PathSpec("random", pl))
        split_strategy = _prompt_choice("Split strategy", ["round_robin", "random"], "round_robin")

    cover_rate = 0.0
    cover_drop_probability = 0.0
    if _prompt_bool("Enable cover traffic?", False):
        cover_rate = float(_prompt("Cover traffic rate (packets/sec)", 5))
        cover_drop_probability = float(_prompt("Cover packet drop probability per hop", 0.0))

    real_rate = float(_prompt("Real traffic rate (packets/sec)", 5))
    crypto_algorithm = _prompt_choice(
        "Crypto algorithm", ["none", "aes256gcm", "chacha20poly1305"], "aes256gcm"
    )

    adversaries = ["global_observer"]
    compromised_fraction = 0.1
    compromise_trials = 2000
    if _prompt_bool("Also run the path-compromise Monte Carlo adversary?", False):
        adversaries.append("path_compromise")
        compromised_fraction = float(_prompt("Compromised node fraction", 0.1))
        compromise_trials = int(_prompt("Monte Carlo trials", 2000))

    config = ExperimentConfig(
        name=name,
        seed=seed,
        duration_s=duration_s,
        num_nodes=num_nodes,
        num_sessions=num_sessions,
        mode="custom",
        routing_strategy="random",
        path_length=path_length,
        extra_paths=extra_paths,
        split_strategy=split_strategy,
        real_rate=real_rate,
        cover_rate=cover_rate,
        cover_drop_probability=cover_drop_probability,
        crypto_algorithm=crypto_algorithm,
        adversaries=adversaries,
        compromised_fraction=compromised_fraction,
        compromise_trials=compromise_trials,
    )

    import yaml

    print("\nAssembled configuration:")
    print(yaml.safe_dump(config.to_dict(), sort_keys=False))
    if not _prompt_bool("Run this experiment now?", True):
        raise SystemExit("Cancelled.")
    return config
