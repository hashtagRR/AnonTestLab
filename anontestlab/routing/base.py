from __future__ import annotations

import random
from abc import ABC, abstractmethod


class RoutingStrategy(ABC):
    """A pluggable node-selection strategy: which relays a circuit uses.

    Circuit *construction* (the telescoping handshake) is always real and
    identical regardless of strategy. That's the transport protocol, not
    a per-experiment choice. Strategies only decide which nodes end up on
    the path.
    """

    name: str = "base"

    @abstractmethod
    def select_path(self, node_ids: list[str], rng: random.Random, path_length: int) -> list[str]:
        ...
