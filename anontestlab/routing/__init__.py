from .base import RoutingStrategy
from .random_path import RandomPathRouting

STRATEGIES: dict[str, type[RoutingStrategy]] = {
    "random": RandomPathRouting,
}


def get_strategy(name: str) -> RoutingStrategy:
    try:
        return STRATEGIES[name]()
    except KeyError:
        raise ValueError(
            f"unknown routing strategy '{name}', available: {sorted(STRATEGIES)}"
        ) from None


__all__ = ["RoutingStrategy", "RandomPathRouting", "STRATEGIES", "get_strategy"]
