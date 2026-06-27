"""Momentum / trend-following — the risk-ON engine.

Buys the strongest trending names: price above its long moving average AND
positive total return over the lookback. Equal-weights the top N. When few
names trend, it stays partly in cash by construction.
"""
from __future__ import annotations

import pandas as pd

from ..indicators import sma_last
from .base import Strategy


class MomentumStrategy(Strategy):
    name = "momentum"

    def target_weights(self, data, universe, context) -> dict[str, float]:
        fast = int(self.params.get("fast", 20))
        slow = int(self.params.get("slow", 100))
        top_n = int(self.params.get("top_n", 4))

        scored: list[tuple[str, float]] = []
        for sym in universe:
            close = self._close(data, sym)
            if close is None or len(close) < slow + 1:
                continue
            slow_ma = sma_last(close, slow)
            fast_ma = sma_last(close, fast)
            last = close.iloc[-1]
            mom = last / close.iloc[-slow] - 1.0          # total return over slow window
            # trend filter: above long MA and fast above slow (confirmed uptrend)
            if pd.notna(slow_ma) and last > slow_ma and fast_ma > slow_ma and mom > 0:
                scored.append((sym, mom))

        scored.sort(key=lambda x: x[1], reverse=True)
        chosen = [s for s, _ in scored[:top_n]]
        return self._equal_weight(chosen, top_n)
