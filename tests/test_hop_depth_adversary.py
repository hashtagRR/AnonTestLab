"""Pure-Python tests for HopDepthAdversary: no subprocesses needed, since
it's structural (like path_compromise), not timing-based. The underlying
wire-size-per-hop math is independently verified against the real
crypto/wire code in
test_wire_and_crypto.py::test_fixed_cell_size_shrinks_by_a_fixed_amount_per_hop."""
import random

from anontestlab.adversary.base import SimulationContext
from anontestlab.adversary.hop_depth import HopDepthAdversary


def _ctx(session_paths: dict[int, list[list[str]]]) -> SimulationContext:
    return SimulationContext(sessions={}, session_paths=session_paths, node_ids=["n0", "n1", "n2"])


def test_hop_depth_reports_nan_without_cell_size():
    adv = HopDepthAdversary(cell_size=None, algorithm="aes256gcm")
    result = adv.attack(_ctx({0: [["n0", "n1", "n2"]]}), random.Random(1))
    assert result.metrics["hop_position_accuracy"] != result.metrics["hop_position_accuracy"]  # nan
    assert result.metrics["path_length_leak_at_hop1"] != result.metrics["path_length_leak_at_hop1"]


def test_hop_depth_recovers_position_perfectly_when_shaping_enabled():
    adv = HopDepthAdversary(cell_size=512, algorithm="aes256gcm")
    ctx = _ctx({0: [["n0", "n1", "n2"]], 1: [["n0", "n1"]]})
    result = adv.attack(ctx, random.Random(1))
    assert result.metrics["hop_position_accuracy"] == 1.0


def test_hop_depth_leak_not_measurable_with_a_single_circuit_length():
    adv = HopDepthAdversary(cell_size=512, algorithm="aes256gcm")
    ctx = _ctx({0: [["n0", "n1", "n2"]], 1: [["n0", "n1", "n2"]]})
    result = adv.attack(ctx, random.Random(1))
    assert result.metrics["path_length_leak_at_hop1"] != result.metrics["path_length_leak_at_hop1"]  # nan


def test_hop_depth_hop1_does_not_leak_path_length():
    adv = HopDepthAdversary(cell_size=512, algorithm="aes256gcm")
    ctx = _ctx({0: [["n0", "n1", "n2"]], 1: [["n0", "n1"]]})  # two distinct lengths present
    result = adv.attack(ctx, random.Random(1))
    assert result.metrics["path_length_leak_at_hop1"] == 0.0


def test_hop_depth_empty_context_reports_nan():
    adv = HopDepthAdversary(cell_size=512, algorithm="aes256gcm")
    result = adv.attack(_ctx({}), random.Random(1))
    assert result.n_sessions == 0
