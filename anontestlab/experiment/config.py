from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml


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

    # WAN realism: applied uniformly to every link in the network (not
    # per-edge), inside the relay forwarding path via asyncio.sleep. No
    # tc/netem/namespaces, so it stays fast local iteration.
    link_latency_ms: float = 0.0
    link_jitter_ms: float = 0.0
    link_loss_probability: float = 0.0
    link_bandwidth_kbps: float | None = None

    observer_bin_width_ms: float = 50.0
    observer_classifier: str = "pearson"
    observer_threshold: float = 0.7

    @property
    def paths(self) -> list[PathSpec]:
        return [PathSpec(self.routing_strategy, self.path_length)] + list(self.extra_paths)

    @property
    def num_paths(self) -> int:
        return 1 + len(self.extra_paths)

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

        return cls(
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
        )

    def to_dict(self) -> dict:
        return asdict(self)
