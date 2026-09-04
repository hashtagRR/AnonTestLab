import random

import pytest

from anontestlab.routing import RandomPathRouting, get_strategy


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
