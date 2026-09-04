from __future__ import annotations

import random

from ..emulator.wire import layer_overhead
from .base import Adversary, AdversaryResult, SimulationContext


class HopDepthAdversary(Adversary):
    """Structural, not timing-based (needs no packets to move, like
    path_compromise): quantifies the fixed-size-cell hop-position leak
    disclosed in the README's Known limitations. Once fixed-size cell
    padding is enabled, the wire size of a cell is a fully deterministic
    function of cell_size, algorithm, and hop position: hop 1 is always
    exactly cell_size bytes regardless of path length (padding is
    computed for the whole circuit up front, see
    circuit_client.py::pad_to_cell_size), and each relay downstream
    strips exactly layer_overhead(algorithm) bytes before forwarding.

    Reports two things: whether an observer at one intermediate hop can
    recover its exact position in the circuit from size alone (yes, once
    shaping is enabled, this is the disclosed leak), and whether an
    observer at hop 1 can tell circuits of different lengths apart from
    size alone (no, that's what the padding is for).
    """

    name = "hop_depth"

    def __init__(self, cell_size: int | None = None, algorithm: str = "none"):
        self.cell_size = cell_size
        self.algorithm = algorithm

    @classmethod
    def from_config(cls, config) -> "HopDepthAdversary":
        return cls(cell_size=config.cell_size, algorithm=config.crypto_algorithm)

    def _hop_size(self, position: int) -> int:
        """position is 1-indexed distance from the client."""
        return self.cell_size - (position - 1) * layer_overhead(self.algorithm)

    def attack(self, ctx: SimulationContext, rng: random.Random) -> AdversaryResult:
        session_ids = list(ctx.session_paths.keys())
        n = len(session_ids)
        if n == 0 or self.cell_size is None:
            return AdversaryResult(
                self.name,
                n,
                {"hop_position_accuracy": float("nan"), "path_length_leak_at_hop1": float("nan")},
            )

        overhead = layer_overhead(self.algorithm)
        correct = 0
        total = 0
        lengths_seen: set[int] = set()
        for sid in session_ids:
            for path in ctx.session_paths[sid]:
                lengths_seen.add(len(path))
                for position in range(1, len(path) + 1):
                    observed_size = self._hop_size(position)
                    predicted_position = round((self.cell_size - observed_size) / overhead) + 1
                    correct += predicted_position == position
                    total += 1

        hop_position_accuracy = correct / total if total else float("nan")

        if len(lengths_seen) < 2:
            # Only one circuit length appears in this experiment, so
            # there's nothing to distinguish between; not measurable here.
            path_length_leak = float("nan")
        else:
            hop1_sizes = {self._hop_size(1) for _ in lengths_seen}
            path_length_leak = 1.0 if len(hop1_sizes) > 1 else 0.0

        return AdversaryResult(
            name=self.name,
            n_sessions=n,
            metrics={
                "hop_position_accuracy": hop_position_accuracy,
                "path_length_leak_at_hop1": path_length_leak,
            },
        )
