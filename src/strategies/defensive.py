"""Defensive — the risk-OFF engine (capital preservation).

Parks the book in the cash-like asset (a short T-bill ETF such as BIL). The
agent rotates here when the market is risk-off, when a halt fires, or when the
two-week preservation rule needs the book defended.
"""
from __future__ import annotations

from .base import Strategy


class DefensiveStrategy(Strategy):
    name = "defensive"

    def target_weights(self, data, universe, context) -> dict[str, float]:
        cash_asset = context.get("cash_asset", "BIL")
        close = self._close(data, cash_asset)
        if close is None or len(close) < 2:
            # No tradable cash ETF data -> hold actual cash (empty book).
            return {}
        return {cash_asset: 1.0}
