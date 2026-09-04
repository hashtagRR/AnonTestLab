from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SessionObservation:
    """What a passive observer sees for one session at whichever paths it
    can watch: packet timestamps only (real packets and undropped cover
    packets look the same to a passive observer, which is the point of
    cover traffic)."""

    session_id: int
    ingress_times: list[float] = field(default_factory=list)
    egress_times: list[float] = field(default_factory=list)


@dataclass
class SimulationContext:
    """Everything an adversary might need, gathered after a run. Timing
    adversaries use `sessions`; structural adversaries (e.g. compromise
    probability) use `session_paths` and `node_ids` instead and can ignore
    timing entirely."""

    sessions: dict[int, SessionObservation]
    session_paths: dict[int, list[list[str]]]  # session_id -> list of paths (each a list of node ids)
    node_ids: list[str]


@dataclass
class AdversaryResult:
    name: str
    n_sessions: int
    metrics: dict[str, float]


class Adversary(ABC):
    name: str = "base"

    @classmethod
    def from_config(cls, config) -> "Adversary":
        return cls()

    @abstractmethod
    def attack(self, ctx: SimulationContext, rng: random.Random) -> AdversaryResult:
        ...
