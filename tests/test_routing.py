import random
from collections import Counter

import pytest

from anontestlab.routing import BandwidthWeightedRouting, RandomPathRouting, get_strategy


def test_random_path_selects_distinct_nodes():
    rng = random.Random(1)
    routing = RandomPathRouting()
    path = routing.select_path([f"n{i}" for i in range(10)], rng, 3)
    assert len(path) == 3
    assert len(set(path)) == 3


def test_random_path_rejects_oversized_request():
    rng = random.Random(1)
    routing = RandomPathRouting()
    with pytest.raises(ValueError):
        routing.select_path(["n0", "n1"], rng, 3)


def test_get_strategy_unknown_raises():
    with pytest.raises(ValueError):
        get_strategy("nonexistent")


def test_bandwidth_weighted_selects_distinct_nodes():
    rng = random.Random(1)
    routing = BandwidthWeightedRouting()
    node_ids = [f"n{i}" for i in range(10)]
    weights = {n: 1.0 for n in node_ids}
    path = routing.select_path(node_ids, rng, 3, weights)
    assert len(path) == 3
    assert len(set(path)) == 3


def test_bandwidth_weighted_rejects_oversized_request():
    rng = random.Random(1)
    routing = BandwidthWeightedRouting()
    with pytest.raises(ValueError):
        routing.select_path(["n0", "n1"], rng, 3, {"n0": 1.0, "n1": 1.0})


def test_bandwidth_weighted_falls_back_to_uniform_without_weights():
    rng = random.Random(1)
    routing = BandwidthWeightedRouting()
    path = routing.select_path([f"n{i}" for i in range(10)], rng, 3, None)
    assert len(path) == 3
    assert len(set(path)) == 3


def test_bandwidth_weighted_favors_higher_weight_nodes():
    rng = random.Random(42)
    routing = BandwidthWeightedRouting()
    node_ids = [f"n{i}" for i in range(5)]
    weights = {"n0": 100.0, "n1": 1.0, "n2": 1.0, "n3": 1.0, "n4": 1.0}
    counts: Counter[str] = Counter()
    for _ in range(500):
        path = routing.select_path(node_ids, rng, 1, weights)
        counts.update(path)
    assert counts["n0"] > counts["n1"] * 10
