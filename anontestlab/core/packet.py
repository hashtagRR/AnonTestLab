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

    @property
    def delivered(self) -> bool:
        return self.delivered_at is not None
