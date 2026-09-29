from dataclasses import fields

from .generators import (
    BurstTraffic,
    ConstantRateTraffic,
    ParetoTraffic,
    PoissonTraffic,
    TrafficGenerator,
)

GENERATORS: dict[str, type[TrafficGenerator]] = {
    "poisson": PoissonTraffic,
    "constant": ConstantRateTraffic,
    "pareto": ParetoTraffic,
    "burst": BurstTraffic,
}


def get_generator(name: str, rate: float, **params) -> TrafficGenerator:
    """Builds the named generator. Extra keyword parameters are passed on
    only when the generator has a field of that name, so callers can pass
    every traffic setting without checking which one applies."""
    try:
        cls = GENERATORS[name]
    except KeyError:
        raise ValueError(
            f"unknown traffic distribution '{name}', available: {sorted(GENERATORS)}"
        ) from None
    accepted = {f.name for f in fields(cls)}
    return cls(rate=rate, **{k: v for k, v in params.items() if k in accepted})


__all__ = [
    "GENERATORS",
    "BurstTraffic",
    "ConstantRateTraffic",
    "ParetoTraffic",
    "PoissonTraffic",
    "TrafficGenerator",
    "get_generator",
]
