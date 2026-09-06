from .generators import (
    ConstantRateTraffic,
    ParetoTraffic,
    PoissonTraffic,
    TrafficGenerator,
)

GENERATORS: dict[str, type[TrafficGenerator]] = {
    "poisson": PoissonTraffic,
    "constant": ConstantRateTraffic,
    "pareto": ParetoTraffic,
}


def get_generator(name: str, rate: float) -> TrafficGenerator:
    try:
        return GENERATORS[name](rate=rate)
    except KeyError:
        raise ValueError(
            f"unknown traffic distribution '{name}', available: {sorted(GENERATORS)}"
        ) from None


__all__ = [
    "GENERATORS",
    "ConstantRateTraffic",
    "ParetoTraffic",
    "PoissonTraffic",
    "TrafficGenerator",
    "get_generator",
]
