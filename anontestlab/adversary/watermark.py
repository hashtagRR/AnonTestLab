from __future__ import annotations

import random

from .base import Adversary, AdversaryResult, SimulationContext


class WatermarkAdversary(Adversary):
    """Active attack: a compromised entry relay (see
    `emulator.orchestrator.WATERMARK_NODE_INDEX`, always pinned to hop 1
    when enabled) delays every `period`-th real packet by a fixed amount.
    This adversary checks whether that pattern is still detectable in the
    *observed* egress inter-arrival gaps, i.e. whether cover traffic and
    cross-traffic buffer against it.

    Best used with a single path per session (`num_paths=1`): egress
    timestamps aren't tracked per-path, so with multiple observed paths
    the gap sequence interleaves arrivals from more than one stream and
    the pattern gets confounded. A known limitation of this simple model,
    not a claim about multi-path robustness.

    Watermark-position membership is keyed by each surviving packet's
    true send-order sequence number (`SessionObservation.egress_seq`),
    not its position in the arrival list: under `link_loss_probability`,
    a packet dropped anywhere downstream of the watermark relay shifts
    every later arrival's *index* without changing its *sequence
    number*, so indexing would silently misattribute gaps for the rest
    of that session.
    """

    name = "watermark"

    def __init__(self, period: int = 0, delay_s: float = 0.0, detection_fraction: float = 0.5):
        self.period = period
        self.delay_s = delay_s
        self.detection_fraction = detection_fraction

    @classmethod
    def from_config(cls, config) -> WatermarkAdversary:
        return cls(period=config.watermark_period, delay_s=config.watermark_delay_ms / 1000.0)

    def attack(self, ctx: SimulationContext, rng: random.Random) -> AdversaryResult:
        sessions = ctx.sessions
        n = len(sessions)
        if n == 0 or self.period <= 0:
            return AdversaryResult(self.name, n, {"watermark_detection_rate": float("nan")})

        detections = 0
        evaluated = 0
        for obs in sessions.values():
            if len(obs.egress_times) < self.period + 1 or not obs.egress_seq:
                continue
            # Sort by arrival time (what a passive observer actually sees,
            # in causal order) but classify each gap by the seq number of
            # the packet that ends it, not its position in this list: loss
            # removes entries without renumbering the survivors, so index
            # and true send position drift apart after the first drop.
            pairs = sorted(zip(obs.egress_times, obs.egress_seq))
            times = [t for t, _ in pairs]
            seqs = [s for _, s in pairs]
            gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
            watermark_gaps = [g for i, g in enumerate(gaps) if seqs[i + 1] % self.period == 0]
            other_gaps = [g for i, g in enumerate(gaps) if seqs[i + 1] % self.period != 0]
            if not watermark_gaps or not other_gaps:
                continue
            evaluated += 1
            mean_watermark = sum(watermark_gaps) / len(watermark_gaps)
            mean_other = sum(other_gaps) / len(other_gaps)
            if mean_watermark - mean_other > self.delay_s * self.detection_fraction:
                detections += 1

        rate = detections / evaluated if evaluated else float("nan")
        return AdversaryResult(
            name=self.name,
            n_sessions=n,
            metrics={"watermark_detection_rate": rate, "watermark_sessions_evaluated": evaluated},
        )
