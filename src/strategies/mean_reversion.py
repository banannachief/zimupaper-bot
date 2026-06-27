"""Mean reversion — the CHOP / range engine.

Buys short-term oversold dips, but ONLY in names that are in a long-term
uptrend (close above the long SMA). This is the classic "buy quality on
weakness" pattern: never catch a falling knife in a downtrend.
"""
from __future__ import annotations

from ..indicators import rsi_last, sma_last
from .base import Strategy


class MeanReversionStrategy(Strategy):
    name = "mean_reversion"

    def target_weights(self, data, universe, context) -> dict[str, float]:
        rsi_period = int(self.params.get("rsi_period", 2))
        rsi_buy = float(self.params.get("rsi_buy", 12))
        sma_filter = int(self.params.get("sma_filter", 200))
        top_n = int(self.params.get("top_n", 4))

        scored: list[tuple[str, float]] = []
        for sym in universe:
            close = self._close(data, sym)
            if close is None or len(close) < sma_filter + 1:
                continue
            trend = sma_last(close, sma_filter)
            r = rsi_last(close, rsi_period)
            last = close.iloc[-1]
            if last > trend and r <= rsi_buy:        # uptrend + oversold dip
                scored.append((sym, r))

        scored.sort(key=lambda x: x[1])              # most oversold first
        chosen = [s for s, _ in scored[:top_n]]
        return self._equal_weight(chosen, top_n)
