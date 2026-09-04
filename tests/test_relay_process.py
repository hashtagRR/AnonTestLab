"""Pure-Python tests for relay_process.py's per-edge link-condition math
and the host<->index helpers it relies on. No subprocesses needed."""
from anontestlab.emulator import wire
from anontestlab.emulator.relay_process import edge_factor


def test_relay_host_index_roundtrip():
    for i in range(10):
        assert wire.relay_index_from_host(wire.relay_host(i)) == i


def test_relay_index_from_host_rejects_non_relay_address():
    import pytest

    with pytest.raises(ValueError):
        wire.relay_index_from_host("10.0.0.5")


def test_edge_factor_is_deterministic():
    assert edge_factor(42, 1, 3, 0.5) == edge_factor(42, 1, 3, 0.5)


def test_edge_factor_is_symmetric():
    assert edge_factor(42, 1, 3, 0.5) == edge_factor(42, 3, 1, 0.5)


def test_edge_factor_stays_within_spread():
    for i, j in [(0, 1), (2, 7), (5, 5)]:
        f = edge_factor(42, i, j, 0.4)
        assert 0.6 <= f <= 1.4


def test_edge_factor_varies_across_different_edges():
    """The whole point of per-edge conditions: different edges from the
    same node get different factors, unlike the flat per-node model."""
    factors = {edge_factor(42, 0, j, 0.5) for j in range(1, 8)}
    assert len(factors) > 1


def test_edge_factor_changes_with_seed():
    assert edge_factor(1, 0, 1, 0.5) != edge_factor(2, 0, 1, 0.5)
