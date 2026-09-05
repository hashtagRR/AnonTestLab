from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Packet:
    """A record of one packet sent through a real circuit: when it was
    sent and, if it made it all the way through, when it was delivered."""

    packet_id: int
    session_id: int
    kind: str  # "real" or "cover"
    path: list[str]
    created_at: float
    delivered_at: float | None = None
    real_seq: int | None = None  # 1-indexed position among this circuit's real sends,
    # independent of cover traffic; used to align with the watermark relay's own count

    @property
    def delivered(self) -> bool:
        return self.delivered_at is not None
