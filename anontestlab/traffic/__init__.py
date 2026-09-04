from .generators import TrafficGenerator, PoissonTraffic, ConstantRateTraffic

GENERATORS: dict[str, type[TrafficGenerator]] = {
    "poisson": PoissonTraffic,
    "constant": ConstantRateTraffic,
}


def get_generator(name: str, rate: float) -> TrafficGenerator:
    try:
        return GENERATORS[name](rate=rate)
    except KeyError:
        raise ValueError(
            f"unknown traffic distribution '{name}', available: {sorted(GENERATORS)}"
        ) from None


__all__ = ["TrafficGenerator", "PoissonTraffic", "ConstantRateTraffic", "GENERATORS", "get_generator"]
