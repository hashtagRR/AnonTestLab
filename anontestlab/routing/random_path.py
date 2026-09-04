from __future__ import annotations

import random

from .base import RoutingStrategy


class RandomPathRouting(RoutingStrategy):
    """Pick `path_length` distinct relays uniformly at random."""

    name = "random"

    def select_path(self, node_ids: list[str], rng: random.Random, path_length: int) -> list[str]:
        if path_length > len(node_ids):
            raise ValueError(
                f"path_length={path_length} exceeds available relays ({len(node_ids)})"
            )
        return rng.sample(node_ids, path_length)
