"""Market-regime detection from the benchmark (SPY).

Classifies the environment so the controller can pick an appropriate
"risk budget" and tilt toward the right kind of strategy. Returns a small,
explainable object — every field shows up in the dashboard's decision log.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..indicators import realized_vol, sma, slope

HIGH_VOL = 0.28      # annualized realized vol above this = stress
SLOPE_FLAT = 0.0002  # per-bar normalized slope magnitude considered "flat"


@dataclass
class Regime:
    label: str          # bull | bear | chop | high_vol
    risk_on: bool
    risk_budget: float  # fraction of equity allowed in risk assets
    vol: float
    above_200dma: bool
    note: str = ""


def detect_regime(bench_close: pd.Series | None) -> Regime:
    if bench_close is None or len(bench_close.dropna()) < 210:
        # Not enough history -> assume cautious neutral.
        return Regime("chop", risk_on=True, risk_budget=0.5, vol=0.0,
                      above_200dma=True, note="insufficient history; neutral")

    close = bench_close.dropna()
    last = close.iloc[-1]
    ma200 = sma(close, 200).iloc[-1]
    ma50 = sma(close, 50).iloc[-1]
    vol = float(realized_vol(close, 20).iloc[-1] or 0.0)
    trend = float(slope(close, 50).iloc[-1] or 0.0)
    above = bool(last > ma200)

    if vol >= HIGH_VOL:
        # Stress: stay defensive but allow a little risk if still above the 200DMA.
        budget = 0.30 if above else 0.10
        return Regime("high_vol", risk_on=above, risk_budget=budget, vol=vol,
                      above_200dma=above, note=f"vol {vol:.0%} >= {HIGH_VOL:.0%}")

    if above and ma50 >= ma200 and trend > SLOPE_FLAT:
        return Regime("bull", risk_on=True, risk_budget=1.0, vol=vol,
                      above_200dma=above, note="uptrend, calm")

    if not above or ma50 < ma200:
        return Regime("bear", risk_on=False, risk_budget=0.20, vol=vol,
                      above_200dma=above, note="below 200DMA / 50<200")

    return Regime("chop", risk_on=True, risk_budget=0.55, vol=vol,
                  above_200dma=above, note="range-bound")
