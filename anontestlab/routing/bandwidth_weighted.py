from __future__ import annotations

import random

from .base import RoutingStrategy


class BandwidthWeightedRouting(RoutingStrategy):
    """Pick `path_length` distinct relays with probability proportional to
    each node's weight (real Tor never picks relays uniformly; it weights
    by advertised bandwidth). Falls back to uniform random if no weights
    are given, or every node has equal weight.

    Sampling without replacement: draw one node weighted by its remaining
    share of total weight, remove it, repeat. Approximates Tor's weighted
    path selection; deliberately doesn't model Tor's guard/exit-flag
    position constraints.
    """

    name = "bandwidth_weighted"

    def select_path(
        self,
        node_ids: list[str],
        rng: random.Random,
        path_length: int,
        weights: dict[str, float] | None = None,
    ) -> list[str]:
        if path_length > len(node_ids):
            raise ValueError(
                f"path_length={path_length} exceeds available relays ({len(node_ids)})"
            )
        if not weights:
            return rng.sample(node_ids, path_length)

        remaining = list(node_ids)
        remaining_weights = [max(weights.get(n, 1.0), 0.0) for n in remaining]
        chosen = []
        for _ in range(path_length):
            total = sum(remaining_weights)
            if total <= 0:
                chosen.extend(rng.sample(remaining, path_length - len(chosen)))
                break
            pick = rng.uniform(0, total)
            acc = 0.0
            for i, w in enumerate(remaining_weights):
                acc += w
                if pick <= acc:
                    break
            else:
                i = len(remaining_weights) - 1  # float rounding: pick landed just past the last edge
            chosen.append(remaining.pop(i))
            remaining_weights.pop(i)
        return chosen
