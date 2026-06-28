"""Backtester — validate the whole stack (strategies + agent + risk) on history
before any paper or real trading.

Drives the SimBroker day by day through ``engine.run_cycle`` so the backtest
exercises the EXACT same code path as live trading. No separate "backtest logic"
to drift out of sync.
"""
from __future__ import annotations

from datetime import timezone

import numpy as np
import pandas as pd

from .broker.sim import SimBroker
from .engine import run_cycle
from .indicators import max_drawdown
from .state import State


def _timeline(history: dict[str, pd.DataFrame], benchmark: str) -> pd.DatetimeIndex:
    idx = history.get(benchmark)
    if idx is not None and not idx.empty:
        base = idx.index
    else:
        base = None
        for df in history.values():
            base = df.index if base is None else base.union(df.index)
    return base.sort_values()


def run_backtest(config, history: dict[str, pd.DataFrame], *,
                 starting_cash: float = 100_000.0, warmup: int = 220,
                 eval_start=None, eval_end=None, return_state: bool = False):
    """Run a backtest. If eval_start/eval_end are given, only trade & measure
    inside that window — earlier bars are still fed to the broker as warmup, so
    there is no lookahead and indicators are fully formed at window open.
    """
    broker = SimBroker(starting_cash=starting_cash)
    broker.set_history(history)
    state = State()
    timeline = _timeline(history, config.benchmark)
    if len(timeline) <= warmup + 5:
        warmup = max(0, len(timeline) - 30)
    es = pd.Timestamp(eval_start) if eval_start is not None else None
    ee = pd.Timestamp(eval_end) if eval_end is not None else None

    for i, d in enumerate(timeline):
        if ee is not None and d > ee:
            break
        prices = {}
        for sym, df in history.items():
            if d in df.index:
                prices[sym] = float(df.loc[d, "close"])
        if not prices:
            continue
        broker.set_as_of(d)
        broker.set_prices(prices)
        in_window = (d >= es) if es is not None else (i >= warmup)
        if not in_window:
            continue
        pd_dt = d.to_pydatetime()
        now = (pd_dt.replace(tzinfo=timezone.utc) if pd_dt.tzinfo is None
               else pd_dt.astimezone(timezone.utc))
        run_cycle(broker, config, state, now=now, market_open=True,
                  render=False, persist=False)

    metrics = _metrics(state, history, config)
    return (metrics, state) if return_state else metrics


def _metrics(state: State, history: dict[str, pd.DataFrame], config) -> dict:
    curve = state.equity_curve
    if len(curve) < 5:
        return {"error": "not enough data", "points": len(curve)}

    eq = pd.Series([p["equity"] for p in curve],
                   index=pd.to_datetime([p["t"] for p in curve]))
    if eq.index.tz is not None:                 # align with tz-naive price history
        eq.index = eq.index.tz_localize(None)
    eq = eq[~eq.index.duplicated(keep="last")].sort_index()

    daily_ret = eq.pct_change().dropna()
    years = max(len(eq) / 252.0, 1e-9)
    total = eq.iloc[-1] / eq.iloc[0] - 1.0
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1.0 / years) - 1.0
    vol = daily_ret.std() * np.sqrt(252.0)
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252.0)) if daily_ret.std() else 0.0
    mdd = max_drawdown(eq)

    weekly = eq.resample("W").last().pct_change().dropna()
    target = config.weekly_gain
    hit = float((weekly >= target).mean()) if len(weekly) else 0.0
    neg = float((weekly < 0).mean()) if len(weekly) else 0.0

    # two-week (non-overlapping) blocks
    biweek = eq.resample("2W").last().pct_change().dropna()
    biweek_neg = float((biweek < 0).mean()) if len(biweek) else 0.0

    bench = history.get(config.benchmark)
    bench_ret = None
    if bench is not None and not bench.empty:
        b = bench["close"].reindex(eq.index).ffill().dropna()
        if len(b) > 1:
            bench_ret = float(b.iloc[-1] / b.iloc[0] - 1.0)

    return {
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "days": len(eq),
        "start_equity": round(float(eq.iloc[0]), 2),
        "end_equity": round(float(eq.iloc[-1]), 2),
        "total_return": round(total, 4),
        "cagr": round(cagr, 4),
        "ann_vol": round(float(vol), 4),
        "sharpe": round(float(sharpe), 2),
        "max_drawdown": round(float(mdd), 4),
        "weekly_target": target,
        "weeks": int(len(weekly)),
        "pct_weeks_hit_target": round(hit, 3),
        "pct_weeks_negative": round(neg, 3),
        "avg_weekly_return": round(float(weekly.mean()) if len(weekly) else 0.0, 4),
        "pct_2wk_blocks_negative": round(biweek_neg, 3),
        "benchmark_return": round(bench_ret, 4) if bench_ret is not None else None,
        "trades": len(state.trades),
    }
