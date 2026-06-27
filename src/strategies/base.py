"""Strategy interface.

A strategy is a pure function of recent market data -> desired portfolio.
It returns **target weights** (fraction of equity) per symbol:
  * long-only (weights >= 0),
  * sum of weights <= 1.0 (any remainder is implicitly cash),
so strategies naturally de-risk when they see few good opportunities.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    name: str = "base"

    def __init__(self, params: dict | None = None):
        self.params = params or {}

    @abstractmethod
    def target_weights(self, data: dict[str, pd.DataFrame], universe: list[str],
                       context: dict) -> dict[str, float]:
        """Return {symbol: weight} with weights in [0,1] summing to <= 1."""

    # -- shared helpers ----------------------------------------------------
    @staticmethod
    def _close(data: dict[str, pd.DataFrame], sym: str) -> pd.Series | None:
        df = data.get(sym)
        if df is None or df.empty or "close" not in df:
            return None
        return df["close"].dropna()

    @staticmethod
    def _equal_weight(symbols: list[str], slots: int) -> dict[str, float]:
        """Equal-weight ``symbols`` over ``slots`` buckets (partial invest if few)."""
        if slots <= 0:
            return {}
        w = 1.0 / slots
        return {s: w for s in symbols}
