"""Dual momentum — relative + absolute momentum (Gary Antonacci style).

A robust, well-documented approach that tends to generalize out-of-sample
because it has few parameters and a strong economic rationale:

  * RELATIVE momentum: rank the universe by total return over a lookback and
    hold the strongest names.
  * ABSOLUTE momentum: only hold a name if its own momentum also clears the
    cash-asset's momentum (a trend/regime filter) — otherwise sit in cash.

So in downtrends it naturally de-risks to cash, and in uptrends it concentrates
on the leaders. Equal-weights the survivors; unfilled slots stay in cash.
"""
from __future__ import annotations

from .base import Strategy


class DualMomentumStrategy(Strategy):
    name = "dual_momentum"

    def target_weights(self, data, universe, context) -> dict[str, float]:
        lookback = int(self.params.get("lookback", 120))   # ~6 months
        top_n = int(self.params.get("top_n", 4))
        cash_asset = context.get("cash_asset", "BIL")

        # absolute-momentum hurdle = cash asset's return over the lookback (or 0)
        cash_close = self._close(data, cash_asset)
        if cash_close is not None and len(cash_close) > lookback:
            hurdle = cash_close.iloc[-1] / cash_close.iloc[-lookback] - 1.0
        else:
            hurdle = 0.0

        scored: list[tuple[str, float]] = []
        for sym in universe:
            close = self._close(data, sym)
            if close is None or len(close) <= lookback:
                continue
            mom = close.iloc[-1] / close.iloc[-lookback] - 1.0
            if mom > hurdle and mom > 0:        # beats cash AND positive
                scored.append((sym, mom))

        scored.sort(key=lambda x: x[1], reverse=True)
        chosen = [s for s, _ in scored[:top_n]]
        return self._equal_weight(chosen, top_n)
