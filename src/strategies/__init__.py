"""Strategy library. The agent rotates capital between these."""
from __future__ import annotations

from .base import Strategy
from .defensive import DefensiveStrategy
from .mean_reversion import MeanReversionStrategy
from .momentum import MomentumStrategy

REGISTRY = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "defensive": DefensiveStrategy,
}


def build_strategies(config) -> dict[str, Strategy]:
    """Instantiate every enabled strategy from config."""
    out: dict[str, Strategy] = {}
    for name, cls in REGISTRY.items():
        cfg = config.strategies.get(name, {})
        if cfg.get("enabled", True):
            out[name] = cls(cfg)
    return out
