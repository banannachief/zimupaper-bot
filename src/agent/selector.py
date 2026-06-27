"""Performance-driven strategy selection — the self-adjusting core.

Each cycle we "shadow-trade" every strategy over the recent window using only
information that was available at each step, score how well it has been working
*lately*, and allocate capital toward the winners. If nothing is working, the
allocation collapses to the defensive book. This is the concrete mechanism for
"adjust the algorithm when the current one isn't working".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RISK_ON = ("momentum", "mean_reversion")
DEFENSIVE = "defensive"


def _common_index(history: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DatetimeIndex:
    idx = None
    for s in symbols:
        df = history.get(s)
        if df is None or df.empty:
            continue
        idx = df.index if idx is None else idx.union(df.index)
    return idx if idx is not None else pd.DatetimeIndex([])


def shadow_returns(strategy, history: dict[str, pd.DataFrame], universe: list[str],
                   cash_asset: str, context: dict, window: int = 20,
                   need: int = 320) -> pd.Series:
    """Hypothetical daily returns if we had followed ``strategy`` recently.

    For each of the last ``window`` trading days, weights are computed from data
    strictly up to the prior close (no lookahead), then applied to that day's
    realized per-symbol return. Uses positional tail-slicing (``need`` bars) so a
    long history doesn't make each step O(n) — this is the backtest hot path.
    """
    symbols = list(dict.fromkeys([*universe, cash_asset]))
    index = _common_index(history, symbols)
    n = len(index)
    if n < window + 2:
        return pd.Series(dtype=float)

    # Precompute per-symbol arrays + index for fast lookup.
    closes = {s: history[s]["close"] for s in symbols
              if s in history and not history[s].empty}

    rets: list[float] = []
    out_dates = []
    start = max(1, n - window)
    for i in range(start, n):
        d, d_prev = index[i], index[i - 1]
        sliced = {}
        for s, _ in closes.items():
            df = history[s]
            pos = df.index.searchsorted(d_prev, side="right")
            if pos >= 2:
                sliced[s] = df.iloc[max(0, pos - need):pos]
        try:
            weights = strategy.target_weights(sliced, universe, context)
        except Exception:
            weights = {}
        day_ret = 0.0
        for sym, w in weights.items():
            c = closes.get(sym)
            if c is None:
                continue
            try:
                p0, p1 = c.get(d_prev), c.get(d)
            except Exception:
                p0 = p1 = None
            if p0 and p1 and p0 > 0:
                day_ret += w * (p1 / p0 - 1.0)
        rets.append(day_ret)
        out_dates.append(d)
    return pd.Series(rets, index=pd.DatetimeIndex(out_dates), dtype=float)


def score_returns(rets: pd.Series) -> float:
    """Risk-adjusted recency score. Positive = working, negative = not working."""
    if rets is None or len(rets) < 3:
        return 0.0
    mean = float(rets.mean())
    std = float(rets.std())
    if std <= 1e-9:
        # No volatility: score on direction of cumulative return.
        return float(np.sign(rets.sum())) * 0.1
    sharpe = mean / std * np.sqrt(252.0)
    # Tilt by total recent return so a strategy in a real drawdown is penalized.
    total = float((1.0 + rets).prod() - 1.0)
    return sharpe + 5.0 * total


def allocate(scores: dict[str, float], risk_budget: float,
             enabled: list[str], min_weight: float = 0.0) -> dict[str, float]:
    """Turn strategy scores + a regime risk budget into strategy weights."""
    risk_names = [n for n in RISK_ON if n in enabled]
    has_def = DEFENSIVE in enabled

    pos = {n: max(0.0, scores.get(n, 0.0)) for n in risk_names}
    pos = {n: v for n, v in pos.items() if v > min_weight}

    weights: dict[str, float] = {}
    if not pos or risk_budget <= 0:
        # Nothing risk-on is working (or no budget) -> defend.
        if has_def:
            return {DEFENSIVE: 1.0}
        return {}

    total = sum(pos.values())
    for n, v in pos.items():
        weights[n] = (v / total) * risk_budget
    if has_def:
        weights[DEFENSIVE] = max(0.0, 1.0 - risk_budget)
    return weights
