"""Host-noise check for the emulator. Relays share one machine, so under
load the operating system's scheduling adds delay that no configured
defense produced, and that delay can look like a timing defense to an
attacker. This check reruns a configuration with relay mixing switched off
and everything else (topology, load, link settings) unchanged. The one-way
entry-to-exit delay that remains is host and link time. A cell passes when
the 95th percentile of that delay, minus the configured link latency, is at
most `limit_fraction` of a reference scale: the smallest nonzero per-hop
mixing delay of the original configuration, or, if it has none, the
smallest attacker bin width.
"""
from __future__ import annotations

import dataclasses

from .config import ExperimentConfig
from .runner import run_experiment


def reference_scale_s(config: ExperimentConfig) -> tuple[float, str]:
    if config.mix_strategy in ("constant", "exponential"):
        return config.mix_delay_ms / 1000.0, "per-hop mixing delay"
    if config.mix_strategy == "pool":
        return config.pool_interval_ms / 2000.0, "mean wait for a pool flush"
    return min(config.suite_bin_widths_s), "smallest attacker bin width"


def run_fidelity(config: ExperimentConfig, limit_fraction: float = 0.1, waves: int = 2) -> dict[str, object]:
    """Reruns the cell with mixing switched off and reports the host-induced
    timing noise. Host load depends on how many sessions run at once, not on
    how many waves follow each other, so in wave mode the probe runs only
    `waves` full waves at the cell's own concurrency instead of every session."""
    sessions = config.num_sessions
    if config.max_concurrent_sessions:
        sessions = min(sessions, waves * config.max_concurrent_sessions)
    probe = dataclasses.replace(config, name=f"{config.name}-fidelity", mix_strategy="none", adversaries=[],
                                num_sessions=sessions)
    metrics = run_experiment(probe).metrics
    link_s = config.path_length * config.link_latency_ms / 1000.0
    noise = metrics["oneway_delay_p95_s"] - link_s
    scale, scale_name = reference_scale_s(config)
    return {
        "oneway_delay_p50_s": metrics["oneway_delay_p50_s"],
        "oneway_delay_p95_s": metrics["oneway_delay_p95_s"],
        "oneway_delay_p99_s": metrics["oneway_delay_p99_s"],
        "configured_link_latency_s": link_s,
        "host_noise_p95_s": noise,
        "reference_scale_s": scale,
        "reference": scale_name,
        "limit_s": limit_fraction * scale,
        "passes": noise <= limit_fraction * scale,
        "delivery_rate": metrics["delivery_rate"],
        "probe_sessions": sessions,
    }
