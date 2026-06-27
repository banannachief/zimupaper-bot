"""Trend-following with volatility-weighted sizing.

Holds every name in a confirmed uptrend (above its long MA, fast MA above slow),
and weights them INVERSELY to recent volatility so each contributes similar risk
(a risk-parity tilt). Calm uptrends get more capital than wild ones; everything
not trending stays in cash. Robust, few parameters.
"""
from __future__ import annotations

import numpy as np

from ..indicators import realized_vol_last, sma_last
from .base import Strategy


class TrendStrategy(Strategy):
    name = "trend"

    def target_weights(self, data, universe, context) -> dict[str, float]:
        fast = int(self.params.get("fast", 50))
        slow = int(self.params.get("slow", 200))
        vol_window = int(self.params.get("vol_window", 20))
        max_names = int(self.params.get("max_names", 8))
        weighting = str(self.params.get("weighting", "inverse_vol"))  # inverse_vol | equal

        candidates: list[tuple[str, float]] = []
        for sym in universe:
            close = self._close(data, sym)
            if close is None or len(close) < slow + 1:
                continue
            ma_slow = sma_last(close, slow)
            ma_fast = sma_last(close, fast)
            last = close.iloc[-1]
            if last > ma_slow and ma_fast > ma_slow:
                vol = float(realized_vol_last(close, vol_window) or 0.0)
                inv = 1.0 / vol if vol > 1e-6 else 0.0
                if inv > 0:
                    candidates.append((sym, inv))

        if not candidates:
            return {}
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:max_names]
        if weighting == "equal":
            # equal weight is far less churny (no daily vol-drift rebalancing)
            w = 1.0 / len(candidates)
            return {s: w for s, _ in candidates}
        total_inv = sum(v for _, v in candidates)
        # inverse-vol: each name contributes similar risk (sum to 1)
        return {s: v / total_inv for s, v in candidates}
