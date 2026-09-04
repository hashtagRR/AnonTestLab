from .base import Adversary, AdversaryResult, SessionObservation, SimulationContext
from .global_observer import GlobalPassiveObserver
from .path_compromise import PathCompromiseAdversary
from .watermark import WatermarkAdversary
from .hop_depth import HopDepthAdversary

ADVERSARIES: dict[str, type[Adversary]] = {
    "global_observer": GlobalPassiveObserver,
    "path_compromise": PathCompromiseAdversary,
    "watermark": WatermarkAdversary,
    "hop_depth": HopDepthAdversary,
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
    "HopDepthAdversary",
    "ADVERSARIES",
    "get_adversary",
]
