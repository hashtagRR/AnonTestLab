from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from ..routing import STRATEGIES


@dataclass
class PathSpec:
    strategy: str = "random"
    path_length: int = 3


@dataclass
class ExperimentConfig:
    name: str
    seed: int = 0
    duration_s: float = 10.0
    grace_period_s: float = 2.0  # time to wait for in-flight packets after the last emission
    num_nodes: int = 10
    num_sessions: int = 5
    mode: str = "custom"  # "tor_like" | "custom": informational preset marker

    baseline: str | None = None  # path to a baseline experiment YAML, diffed into report.md

    # Path 0's routing (flat fields, kept sweepable/backward-compatible).
    routing_strategy: str = "random"
    path_length: int = 3
    # Paths 1..N-1, for traffic-splitting across independent paths.
    extra_paths: list[PathSpec] = field(default_factory=list)
    split_strategy: str = "round_robin"  # "round_robin" | "random"

    real_traffic_distribution: str = "poisson"
    real_rate: float = 5.0
    cover_traffic_distribution: str = "poisson"
    cover_rate: float = 0.0
    cover_drop_probability: float = 0.0

    crypto_algorithm: str = "none"  # "none" | "aes256gcm" | "chacha20poly1305"

    cell_size: int | None = None  # None = no shaping; else every cell is padded to this many wire bytes

    traffic_mode: str = "variable"  # "variable" | "fixed_rate"
    fixed_rate: float = 20.0  # packets/sec on the wire when traffic_mode == "fixed_rate"

    observed_path_count: int | None = None  # None = adversary observes every path

    # AS-level partial observer: when num_as_groups > 1, relays are split into
    # mock AS groups and the observer sees a path's entry/exit independently,
    # based on whether that hop's AS is one of the observed_as_count observed
    # ones; this replaces observed_path_count when enabled.
    num_as_groups: int = 1
    observed_as_count: int | None = None

    adversaries: list[str] = field(default_factory=lambda: ["global_observer"])
    compromised_fraction: float = 0.1
    compromise_trials: int = 2000

    # Active watermarking: a designated relay (always pinned to hop 1) delays
    # every `watermark_period`-th real packet by `watermark_delay_ms`. The
    # WatermarkAdversary then checks whether that pattern is still visible
    # in the observed egress timing. watermark_period=0 disables it.
    watermark_period: int = 0
    watermark_delay_ms: float = 30.0

    # WAN realism, inside the relay forwarding path via asyncio.sleep. No
    # tc/netem/namespaces, so it stays fast local iteration. Every node
    # shares these base values unless link_heterogeneous scales each
    # node's values by its own factor (still per-node, not truly
    # per-edge: the same relay behaves identically toward every peer).
    link_latency_ms: float = 0.0
    link_jitter_ms: float = 0.0
    link_loss_probability: float = 0.0
    link_bandwidth_kbps: float | None = None
    link_heterogeneous: bool = False
    link_heterogeneity_spread: float = 0.5  # each node's factor ~ Uniform(1-spread, 1+spread)

    observer_bin_width_ms: float = 50.0
    observer_classifier: str = "pearson"
    observer_threshold: float = 0.7

    @property
    def paths(self) -> list[PathSpec]:
        return [PathSpec(self.routing_strategy, self.path_length)] + list(self.extra_paths)

    @property
    def num_paths(self) -> int:
        return 1 + len(self.extra_paths)

    def validate(self) -> None:
        """Raise ValueError with every problem found, rather than letting
        a bad value fail confusingly deep in the emulator (or not at
        all until a division by zero, a relay subprocess exceeding the
        loopback-subnet limit, etc)."""
        errors: list[str] = []

        def check(condition: bool, message: str) -> None:
            if not condition:
                errors.append(message)

        check(self.duration_s > 0, f"duration_s must be positive, got {self.duration_s}")
        check(self.num_nodes > 0, f"num_nodes must be positive, got {self.num_nodes}")
        check(self.num_nodes <= 254, f"num_nodes={self.num_nodes} exceeds the 254-relay loopback-subnet limit")
        check(self.num_sessions > 0, f"num_sessions must be positive, got {self.num_sessions}")
        check(self.real_rate >= 0, f"real_rate must be non-negative, got {self.real_rate}")
        check(self.cover_rate >= 0, f"cover_rate must be non-negative, got {self.cover_rate}")
        check(
            0 <= self.cover_drop_probability <= 1,
            f"cover_drop_probability must be in [0, 1], got {self.cover_drop_probability}",
        )
        check(
            self.traffic_mode in ("variable", "fixed_rate"),
            f"traffic_mode must be 'variable' or 'fixed_rate', got {self.traffic_mode!r}",
        )
        if self.traffic_mode == "fixed_rate":
            check(self.fixed_rate > 0, f"fixed_rate must be positive, got {self.fixed_rate}")
            if self.fixed_rate > 0 and self.real_rate >= self.fixed_rate:
                warnings.warn(
                    f"real_rate ({self.real_rate}) >= fixed_rate ({self.fixed_rate}): sustained real "
                    "demand at or above the fixed-rate schedule's capacity means the backlog will "
                    "keep growing rather than draining, so the session will run well past duration_s. "
                    "Lower real_rate or raise fixed_rate unless that queue growth is what you're "
                    "studying.",
                    stacklevel=2,
                )
        if self.cell_size is not None:
            check(self.cell_size > 0, f"cell_size must be positive, got {self.cell_size}")
        check(
            self.crypto_algorithm in ("none", "aes256gcm", "chacha20poly1305"),
            f"crypto_algorithm must be one of none/aes256gcm/chacha20poly1305, got {self.crypto_algorithm!r}",
        )
        check(
            self.split_strategy in ("round_robin", "random"),
            f"split_strategy must be 'round_robin' or 'random', got {self.split_strategy!r}",
        )
        for spec in self.paths:
            check(
                spec.strategy in STRATEGIES,
                f"routing strategy {spec.strategy!r} unknown, available: {sorted(STRATEGIES)}",
            )
        for i, spec in enumerate(self.paths):
            if spec.path_length <= 0:
                errors.append(f"path {i}: path_length must be positive, got {spec.path_length}")
            elif spec.path_length > self.num_nodes:
                errors.append(
                    f"path {i}: path_length={spec.path_length} exceeds num_nodes={self.num_nodes}"
                )
        check(self.num_as_groups > 0, f"num_as_groups must be positive, got {self.num_as_groups}")
        if self.observed_path_count is not None:
            check(self.observed_path_count > 0, f"observed_path_count must be positive if set, got {self.observed_path_count}")
        if self.observed_as_count is not None:
            check(self.observed_as_count > 0, f"observed_as_count must be positive if set, got {self.observed_as_count}")
        check(
            0 <= self.compromised_fraction <= 1,
            f"compromised_fraction must be in [0, 1], got {self.compromised_fraction}",
        )
        check(self.compromise_trials >= 0, f"compromise_trials must be non-negative, got {self.compromise_trials}")
        check(self.watermark_period >= 0, f"watermark_period must be non-negative, got {self.watermark_period}")
        check(self.link_latency_ms >= 0, f"link_latency_ms must be non-negative, got {self.link_latency_ms}")
        check(self.link_jitter_ms >= 0, f"link_jitter_ms must be non-negative, got {self.link_jitter_ms}")
        check(
            0 <= self.link_loss_probability <= 1,
            f"link_loss_probability must be in [0, 1], got {self.link_loss_probability}",
        )
        if self.link_bandwidth_kbps is not None:
            check(self.link_bandwidth_kbps > 0, f"link_bandwidth_kbps must be positive if set, got {self.link_bandwidth_kbps}")
        check(
            0 <= self.link_heterogeneity_spread < 1,
            f"link_heterogeneity_spread must be in [0, 1), got {self.link_heterogeneity_spread}",
        )

        if errors:
            raise ValueError("invalid experiment config:\n  - " + "\n  - ".join(errors))

    @classmethod
    def tor_like(cls, name: str, **overrides) -> "ExperimentConfig":
        base = dict(
            name=name,
            mode="tor_like",
            routing_strategy="random",
            path_length=3,
            extra_paths=[],
            cover_rate=0.0,
            cover_drop_probability=0.0,
        )
        base.update(overrides)
        return cls(**base)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ExperimentConfig":
        raw = yaml.safe_load(Path(path).read_text())
        exp = raw.get("experiment", {})
        network = raw.get("network", {})
        routing = raw.get("routing", {})
        traffic = raw.get("traffic", {})
        cover_behaviour = raw.get("cover_behaviour", {})
        crypto = raw.get("crypto", {})
        traffic_shaping = raw.get("traffic_shaping", {})
        link_conditions = raw.get("link_conditions", {})
        adversary = raw.get("adversary", {})
        sessions = raw.get("sessions", {})

        if "name" not in exp:
            raise ValueError("experiment.name is required")

        if "paths" in routing:
            path_dicts = routing["paths"]
            routing_strategy = path_dicts[0].get("strategy", cls.routing_strategy)
            path_length = path_dicts[0].get("path_length", cls.path_length)
            extra_paths = [
                PathSpec(p.get("strategy", cls.routing_strategy), p.get("path_length", cls.path_length))
                for p in path_dicts[1:]
            ]
        else:
            routing_strategy = routing.get("strategy", cls.routing_strategy)
            path_length = routing.get("path_length", cls.path_length)
            extra_paths = []

        observed_paths = adversary.get("observed_paths", "all")
        observed_path_count = None if observed_paths == "all" else int(observed_paths)

        observed_as = adversary.get("observed_as", "all")
        observed_as_count = None if observed_as == "all" else int(observed_as)

        observation_cfg = adversary.get("observation", {})
        classifier_cfg = adversary.get("classifier", {})
        watermark_cfg = adversary.get("watermark", {})

        adversary_types = adversary.get("types")
        if adversary_types is None:
            adversary_types = [adversary.get("type", "global_observer")]

        baseline_path = raw.get("baseline")
        if baseline_path is not None:
            baseline_path = str((Path(path).parent / baseline_path).resolve())

        config = cls(
            name=exp["name"],
            baseline=baseline_path,
            seed=exp.get("seed", cls.seed),
            duration_s=exp.get("duration_s", cls.duration_s),
            grace_period_s=exp.get("grace_period_s", cls.grace_period_s),
            num_nodes=network.get("nodes", cls.num_nodes),
            num_as_groups=network.get("as_groups", cls.num_as_groups),
            num_sessions=sessions.get("count", cls.num_sessions),
            mode=exp.get("mode", cls.mode),
            routing_strategy=routing_strategy,
            path_length=path_length,
            extra_paths=extra_paths,
            split_strategy=routing.get("split_strategy", cls.split_strategy),
            real_traffic_distribution=traffic.get("distribution", cls.real_traffic_distribution),
            real_rate=traffic.get("real_rate", cls.real_rate),
            cover_traffic_distribution=traffic.get(
                "cover_distribution", cls.cover_traffic_distribution
            ),
            cover_rate=traffic.get("cover_rate", cls.cover_rate),
            cover_drop_probability=cover_behaviour.get(
                "drop_probability", cls.cover_drop_probability
            ),
            crypto_algorithm=crypto.get("algorithm", cls.crypto_algorithm),
            cell_size=traffic_shaping.get("cell_size") if traffic_shaping.get("enabled") else None,
            traffic_mode=traffic_shaping.get("mode", cls.traffic_mode),
            fixed_rate=traffic_shaping.get("rate", cls.fixed_rate),
            observed_path_count=observed_path_count,
            observed_as_count=observed_as_count,
            adversaries=adversary_types,
            compromised_fraction=adversary.get("compromised_fraction", cls.compromised_fraction),
            compromise_trials=adversary.get("compromise_trials", cls.compromise_trials),
            observer_bin_width_ms=observation_cfg.get("bin_width_ms", cls.observer_bin_width_ms),
            observer_classifier=classifier_cfg.get("type", cls.observer_classifier),
            observer_threshold=classifier_cfg.get("threshold", cls.observer_threshold),
            watermark_period=watermark_cfg.get("period", cls.watermark_period),
            watermark_delay_ms=watermark_cfg.get("delay_ms", cls.watermark_delay_ms),
            link_latency_ms=link_conditions.get("latency_ms", cls.link_latency_ms),
            link_jitter_ms=link_conditions.get("jitter_ms", cls.link_jitter_ms),
            link_loss_probability=link_conditions.get("loss_probability", cls.link_loss_probability),
            link_bandwidth_kbps=link_conditions.get("bandwidth_kbps", cls.link_bandwidth_kbps),
            link_heterogeneous=link_conditions.get("heterogeneous", cls.link_heterogeneous),
            link_heterogeneity_spread=link_conditions.get(
                "heterogeneity_spread", cls.link_heterogeneity_spread
            ),
        )
        config.validate()
        return config

    def to_dict(self) -> dict:
        return asdict(self)
