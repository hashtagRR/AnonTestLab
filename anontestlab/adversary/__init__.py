from .base import Adversary, AdversaryResult, SessionObservation, SimulationContext
from .global_observer import GlobalPassiveObserver
from .path_compromise import PathCompromiseAdversary
from .watermark import WatermarkAdversary

ADVERSARIES: dict[str, type[Adversary]] = {
    "global_observer": GlobalPassiveObserver,
    "path_compromise": PathCompromiseAdversary,
    "watermark": WatermarkAdversary,
}


def get_adversary(name: str, config) -> Adversary:
    try:
        return ADVERSARIES[name].from_config(config)
    except KeyError:
        raise ValueError(
            f"unknown adversary '{name}', available: {sorted(ADVERSARIES)}"
        ) from None


__all__ = [
    "Adversary",
    "AdversaryResult",
    "SessionObservation",
    "SimulationContext",
    "GlobalPassiveObserver",
    "PathCompromiseAdversary",
    "WatermarkAdversary",
    "ADVERSARIES",
    "get_adversary",
]
