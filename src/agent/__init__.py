"""The agentic meta-controller: regime detection + performance-driven strategy
selection + self-adjustment triggers."""
from .controller import Controller, Decision  # noqa: F401
from .regime import Regime, detect_regime  # noqa: F401
