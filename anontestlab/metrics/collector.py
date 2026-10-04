from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..core.packet import Packet


@dataclass
class MetricsCollector:
    packets: list[Packet] = field(default_factory=list)

    def record(self, packet: Packet) -> None:
        self.packets.append(packet)

    def oneway_delays_s(self) -> list[float]:
        """Sorted entry-to-exit delay of every delivered real packet. The
        summary below only keeps p50/p95/p99 of this; callers that want
        the full empirical distribution (a CDF, a histogram) need the raw
        values, which live only in memory during the run unless a caller
        persists this."""
        delivered_real = [p for p in self.packets if p.kind == "real" and p.delivered]
        return sorted(p.exit_at - p.created_at for p in delivered_real if p.exit_at is not None)

    def summary(self) -> dict[str, float]:
        real = [p for p in self.packets if p.kind == "real"]
        cover = [p for p in self.packets if p.kind == "cover"]
        delivered_real = [p for p in real if p.delivered]
        latencies = [p.delivered_at - p.created_at for p in delivered_real]

        delivery_rate = len(delivered_real) / len(real) if real else float("nan")
        avg_latency = statistics.mean(latencies) if latencies else float("nan")
        p95_latency = (
            statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else avg_latency
        )
        bandwidth_overhead = (len(real) + len(cover)) / len(real) if real else float("nan")
        oneway = self.oneway_delays_s()

        return {
            "real_packets_sent": len(real),
            "cover_packets_sent": len(cover),
            "real_packets_delivered": len(delivered_real),
            "delivery_rate": delivery_rate,
            "avg_latency_s": avg_latency,
            "p95_latency_s": p95_latency,
            "bandwidth_overhead_x": bandwidth_overhead,
            "oneway_delay_p50_s": _quantile(oneway, 0.50),
            "oneway_delay_p95_s": _quantile(oneway, 0.95),
            "oneway_delay_p99_s": _quantile(oneway, 0.99),
        }


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]
