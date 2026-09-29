from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from ..crypto import ALGORITHMS as CRYPTO_ALGORITHMS
from ..emulator.crypto_layer import KEYEXCHANGES
from ..emulator.mixing import STRATEGIES as MIX_STRATEGIES
from ..emulator.splitting import POLICIES as SPLIT_POLICIES
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
    max_concurrent_sessions: int | None = None  # run sessions in waves of this size; timestamps become per-session
    mode: str = "custom"  # "tor_like" | "custom": informational preset marker

    baseline: str | None = None  # path to a baseline experiment YAML, diffed into report.md

    # Path 0's routing (flat fields, kept sweepable/backward-compatible).
    routing_strategy: str = "random"
    path_length: int = 3
    # Paths 1..N-1, for traffic-splitting across independent paths.
    extra_paths: list[PathSpec] = field(default_factory=list)
    split_strategy: str = "round_robin"  # see emulator/splitting.py: round_robin | random | iid | batch | latency
    split_weights: list[float] | None = None  # per-leg fractions (iid, batch, weighted round_robin); None = even
    split_batch_mean_s: float = 2.0  # batch policy: mean batch duration
    split_leg_rtt_ms: list[float] | None = None  # latency policy: nominal RTT per leg; None = 50, 100, 150, ...
    split_leg_window: int = 8  # latency policy: cells a leg may have in flight within one RTT
    merge: str = "disjoint"  # "disjoint" | "common_exit" (all legs end at one exit relay, Conflux-style)

    real_traffic_distribution: str = "poisson"
    real_rate: float = 5.0
    burst_mean_cells: float = 12.0  # "burst" distribution: mean cells per burst
    burst_gap_ms: float = 2.0  # "burst" distribution: gap between cells of one burst
    cover_traffic_distribution: str = "poisson"
    cover_rate: float = 0.0
    cover_drop_probability: float = 0.0
    # "per_hop": each intermediate hop drops each cover cell with
    # cover_drop_probability. "random_hop": the client picks one hop per cover
    # cell uniformly along the path and only that hop absorbs it (decoy
    # termination); cover_drop_probability is ignored.
    cover_drop_mode: str = "per_hop"

    crypto_algorithm: str = "none"  # see anontestlab.crypto.ALGORITHMS for the full set
    crypto_keyexchange: str = "x25519"  # "x25519" | "x448" | "p256", the handshake curve

    cell_size: int | None = None  # None = no shaping; else every cell is padded to this many wire bytes

    traffic_mode: str = "variable"  # "variable" | "fixed_rate"
    fixed_rate: float = 20.0  # packets/sec on the wire when traffic_mode == "fixed_rate"

    observed_path_count: int | None = None  # None = adversary observes every path
    observed_legs: list[int] | None = None  # explicit entry-side legs the adversary sees; overrides observed_path_count
    egress_observation: str = "per_path"  # "per_path" | "merged" (exit side sees every leg's cells)

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
    # node's values by its own factor, or link_per_edge additionally
    # scales a relay's forward-direction send to a specific peer by a
    # factor for that (relay, peer) pair (see relay_process.py::edge_factor
    # for why this is directional only).
    link_latency_ms: float = 0.0
    link_jitter_ms: float = 0.0
    link_loss_probability: float = 0.0
    link_bandwidth_kbps: float | None = None
    link_heterogeneous: bool = False
    link_heterogeneity_spread: float = 0.5  # each node's (or edge's) factor ~ Uniform(1-spread, 1+spread)
    link_per_edge: bool = False

    # Relay-side mixing, applied at every hop to data cells (see
    # emulator/mixing.py): "none" | "constant" | "exponential" | "pool".
    mix_strategy: str = "none"
    mix_delay_ms: float = 0.0  # constant delay, or the exponential mean, per hop
    pool_interval_ms: float = 100.0  # pool flush period
    pool_release_probability: float = 1.0  # 1.0 = empty the pool each flush; < 1 = retained/binomial pool
    pool_interval_jitter: float = 0.0  # randomized flush: interval * (1 +/- U(jitter)), in [0, 1)

    observer_bin_width_ms: float = 50.0
    observer_classifier: str = "pearson"
    observer_threshold: float = 0.7
    # 0 = in-sample TPR@FPR (cut chosen on the same impostor pairs it's reported
    # against). > 0 = hold out: this fraction of sessions calibrates the cut and
    # the rest are scored, so the threshold never sees the pairs it's judged on.
    observer_calibration_fraction: float = 0.0

    # correlation_suite adversary (adversary/correlation_suite.py)
    suite_attackers: list[str] = field(default_factory=lambda: ["a0", "a1", "a2", "a3"])
    suite_bin_widths_s: list[float] = field(default_factory=lambda: [0.1, 0.25, 0.5, 1.0])
    suite_lag_max_s: float | None = None  # None = max(2 s, P99 of added delay) + 0.5 s
    suite_psi: list[float] = field(default_factory=lambda: [0.9, 0.99])
    suite_base_rates: list[float] = field(default_factory=lambda: [1e-4, 1e-3, 1e-5])
    suite_fpr_targets: list[float] = field(default_factory=lambda: [1e-3, 1e-4])
    suite_window_quantiles: list[float] = field(default_factory=lambda: [0.5, 0.95])
    suite_latency_floor_ms: float = 20.0  # added to A3 windows for processing and link time outside the delay model
    suite_lr_step_ms: float = 10.0  # time grid of the likelihood-ratio attacker

    @property
    def paths(self) -> list[PathSpec]:
        return [PathSpec(self.routing_strategy, self.path_length), *self.extra_paths]

    @property
    def expected_mix_delay_per_hop_s(self) -> float:
        """Mean added delay per hop from mixing alone (0 for 'none')."""
        if self.mix_strategy in ("constant", "exponential"):
            return self.mix_delay_ms / 1000.0
        if self.mix_strategy == "pool" and self.pool_release_probability > 0:
            # wait for the next flush (~half an interval) plus a geometric
            # number of further flushes before release
            interval = self.pool_interval_ms / 1000.0
            return interval * (0.5 + (1 - self.pool_release_probability) / self.pool_release_probability)
        return 0.0

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
        if self.max_concurrent_sessions is not None:
            check(
                self.max_concurrent_sessions > 0,
                f"max_concurrent_sessions must be positive if set, got {self.max_concurrent_sessions}",
            )
        check(self.real_rate >= 0, f"real_rate must be non-negative, got {self.real_rate}")
        check(self.burst_mean_cells >= 1, f"burst_mean_cells must be at least 1, got {self.burst_mean_cells}")
        check(self.burst_gap_ms >= 0, f"burst_gap_ms must be non-negative, got {self.burst_gap_ms}")
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
            self.crypto_algorithm in CRYPTO_ALGORITHMS,
            f"crypto_algorithm {self.crypto_algorithm!r} unknown, available: {sorted(CRYPTO_ALGORITHMS)}",
        )
        check(
            self.crypto_keyexchange in KEYEXCHANGES,
            f"crypto_keyexchange {self.crypto_keyexchange!r} unknown, available: {sorted(KEYEXCHANGES)}",
        )
        check(
            self.split_strategy in SPLIT_POLICIES,
            f"split_strategy {self.split_strategy!r} unknown, available: {list(SPLIT_POLICIES)}",
        )
        if self.split_weights is not None:
            check(
                len(self.split_weights) == self.num_paths and all(w > 0 for w in self.split_weights),
                f"split_weights needs {self.num_paths} positive values, got {self.split_weights}",
            )
        check(self.split_batch_mean_s > 0, f"split_batch_mean_s must be positive, got {self.split_batch_mean_s}")
        if self.split_leg_rtt_ms is not None:
            check(
                len(self.split_leg_rtt_ms) == self.num_paths and all(r > 0 for r in self.split_leg_rtt_ms),
                f"split_leg_rtt_ms needs {self.num_paths} positive values, got {self.split_leg_rtt_ms}",
            )
        check(self.split_leg_window > 0, f"split_leg_window must be positive, got {self.split_leg_window}")
        check(
            self.merge in ("disjoint", "common_exit"),
            f"merge must be 'disjoint' or 'common_exit', got {self.merge!r}",
        )
        if self.merge == "common_exit":
            needed = sum(spec.path_length - 1 for spec in self.paths) + 1
            check(needed <= self.num_nodes, f"common_exit needs {needed} distinct relays, num_nodes={self.num_nodes}")
        if self.observed_legs is not None:
            check(
                len(self.observed_legs) > 0 and all(0 <= i < self.num_paths for i in self.observed_legs),
                f"observed_legs must list leg indices in 0..{self.num_paths - 1}, got {self.observed_legs}",
            )
        check(
            self.egress_observation in ("per_path", "merged"),
            f"egress_observation must be 'per_path' or 'merged', got {self.egress_observation!r}",
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
            check(
                self.observed_path_count > 0,
                f"observed_path_count must be positive if set, got {self.observed_path_count}",
            )
        if self.observed_as_count is not None:
            check(
                self.observed_as_count > 0,
                f"observed_as_count must be positive if set, got {self.observed_as_count}",
            )
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
            check(
                self.link_bandwidth_kbps > 0,
                f"link_bandwidth_kbps must be positive if set, got {self.link_bandwidth_kbps}",
            )
        check(
            0 <= self.link_heterogeneity_spread < 1,
            f"link_heterogeneity_spread must be in [0, 1), got {self.link_heterogeneity_spread}",
        )

        check(
            self.cover_drop_mode in ("per_hop", "random_hop"),
            f"cover_drop_mode must be 'per_hop' or 'random_hop', got {self.cover_drop_mode!r}",
        )
        check(
            self.mix_strategy in MIX_STRATEGIES,
            f"mix_strategy {self.mix_strategy!r} unknown, available: {list(MIX_STRATEGIES)}",
        )
        if self.mix_strategy in ("constant", "exponential"):
            check(
                self.mix_delay_ms > 0,
                f"mix_delay_ms must be positive for {self.mix_strategy}, got {self.mix_delay_ms}",
            )
        if self.mix_strategy == "pool":
            check(
                self.pool_interval_ms > 0, f"pool_interval_ms must be positive, got {self.pool_interval_ms}"
            )
            check(
                0 < self.pool_release_probability <= 1,
                f"pool_release_probability must be in (0, 1], got {self.pool_release_probability}",
            )
            check(
                0 <= self.pool_interval_jitter < 1,
                f"pool_interval_jitter must be in [0, 1), got {self.pool_interval_jitter}",
            )
        per_hop_s = self.expected_mix_delay_per_hop_s
        max_hops = max(spec.path_length for spec in self.paths)
        if per_hop_s * max_hops * 3 > self.grace_period_s:
            warnings.warn(
                f"mixing adds ~{per_hop_s * max_hops:.2f}s mean delay over {max_hops} hops, but "
                f"grace_period_s={self.grace_period_s}: cells still in a mix when the session "
                "closes are lost and never reach the egress observer. Raise grace_period_s to "
                "a few times the mean added delay.",
                stacklevel=2,
            )
        check(
            0 <= self.observer_calibration_fraction < 1,
            f"observer_calibration_fraction must be in [0, 1), got {self.observer_calibration_fraction}",
        )

        check(
            set(self.suite_attackers) <= {"a0", "a1", "a2", "a3"},
            f"suite_attackers must be drawn from a0, a1, a2, a3, got {self.suite_attackers}",
        )
        check(all(w > 0 for w in self.suite_bin_widths_s), "suite_bin_widths_s must be positive")
        check(all(0 < p < 1 for p in self.suite_psi), "suite_psi values must be in (0, 1)")
        check(all(0 < b < 1 for b in self.suite_base_rates), "suite_base_rates values must be in (0, 1)")
        check(all(0 < q < 1 for q in self.suite_window_quantiles), "suite_window_quantiles must be in (0, 1)")

        if errors:
            raise ValueError("invalid experiment config:\n  - " + "\n  - ".join(errors))

    @classmethod
    def tor_like(cls, name: str, **overrides) -> ExperimentConfig:
        base = {
            "name": name,
            "mode": "tor_like",
            "routing_strategy": "random",
            "path_length": 3,
            "extra_paths": [],
            "cover_rate": 0.0,
            "cover_drop_probability": 0.0,
        }
        base.update(overrides)
        return cls(**base)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExperimentConfig:
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
        observed_legs = adversary.get("observed_legs")

        observed_as = adversary.get("observed_as", "all")
        observed_as_count = None if observed_as == "all" else int(observed_as)

        observation_cfg = adversary.get("observation", {})
        classifier_cfg = adversary.get("classifier", {})
        watermark_cfg = adversary.get("watermark", {})
        evaluation_cfg = adversary.get("evaluation", {})
        mixing = raw.get("mixing", {})
        suite_cfg = adversary.get("correlation_suite", {})

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
            max_concurrent_sessions=sessions.get("max_concurrent"),
            mode=exp.get("mode", cls.mode),
            routing_strategy=routing_strategy,
            path_length=path_length,
            extra_paths=extra_paths,
            split_strategy=routing.get("split_strategy", cls.split_strategy),
            split_weights=routing.get("split_weights"),
            split_batch_mean_s=routing.get("split_batch_mean_s", cls.split_batch_mean_s),
            split_leg_rtt_ms=routing.get("split_leg_rtt_ms"),
            split_leg_window=routing.get("split_leg_window", cls.split_leg_window),
            merge=routing.get("merge", cls.merge),
            real_traffic_distribution=traffic.get("distribution", cls.real_traffic_distribution),
            real_rate=traffic.get("real_rate", cls.real_rate),
            burst_mean_cells=traffic.get("burst_mean_cells", cls.burst_mean_cells),
            burst_gap_ms=traffic.get("burst_gap_ms", cls.burst_gap_ms),
            cover_traffic_distribution=traffic.get(
                "cover_distribution", cls.cover_traffic_distribution
            ),
            cover_rate=traffic.get("cover_rate", cls.cover_rate),
            cover_drop_probability=cover_behaviour.get(
                "drop_probability", cls.cover_drop_probability
            ),
            cover_drop_mode=cover_behaviour.get("drop_mode", cls.cover_drop_mode),
            mix_strategy=mixing.get("strategy", cls.mix_strategy),
            mix_delay_ms=mixing.get("delay_ms", cls.mix_delay_ms),
            pool_interval_ms=mixing.get("pool_interval_ms", cls.pool_interval_ms),
            pool_release_probability=mixing.get("release_probability", cls.pool_release_probability),
            pool_interval_jitter=mixing.get("interval_jitter", cls.pool_interval_jitter),
            crypto_algorithm=crypto.get("algorithm", cls.crypto_algorithm),
            crypto_keyexchange=crypto.get("keyexchange", cls.crypto_keyexchange),
            cell_size=traffic_shaping.get("cell_size") if traffic_shaping.get("enabled") else None,
            traffic_mode=traffic_shaping.get("mode", cls.traffic_mode),
            fixed_rate=traffic_shaping.get("rate", cls.fixed_rate),
            observed_path_count=observed_path_count,
            observed_legs=observed_legs,
            egress_observation=adversary.get("egress_observation", cls.egress_observation),
            observed_as_count=observed_as_count,
            adversaries=adversary_types,
            compromised_fraction=adversary.get("compromised_fraction", cls.compromised_fraction),
            compromise_trials=adversary.get("compromise_trials", cls.compromise_trials),
            observer_bin_width_ms=observation_cfg.get("bin_width_ms", cls.observer_bin_width_ms),
            observer_classifier=classifier_cfg.get("type", cls.observer_classifier),
            observer_threshold=classifier_cfg.get("threshold", cls.observer_threshold),
            suite_attackers=suite_cfg.get("attackers", ["a0", "a1", "a2", "a3"]),
            suite_bin_widths_s=suite_cfg.get("bin_widths_s", [0.1, 0.25, 0.5, 1.0]),
            suite_lag_max_s=suite_cfg.get("lag_max_s"),
            suite_psi=suite_cfg.get("psi", [0.9, 0.99]),
            suite_base_rates=suite_cfg.get("base_rates", [1e-4, 1e-3, 1e-5]),
            suite_fpr_targets=suite_cfg.get("fpr_targets", [1e-3, 1e-4]),
            suite_window_quantiles=suite_cfg.get("window_quantiles", [0.5, 0.95]),
            suite_latency_floor_ms=suite_cfg.get("latency_floor_ms", 20.0),
            suite_lr_step_ms=suite_cfg.get("lr_step_ms", 10.0),
            observer_calibration_fraction=evaluation_cfg.get(
                "calibration_fraction", cls.observer_calibration_fraction
            ),
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
            link_per_edge=link_conditions.get("per_edge", cls.link_per_edge),
        )
        config.validate()
        return config

    def to_dict(self) -> dict:
        return asdict(self)
