#!/usr/bin/env python3
"""Compare candidate strategy combinations across an older period and a recent
OUT-OF-SAMPLE holdout. These strategies are low-parameter (little to overfit),
so the honest test is simply: does it hold up on recent, unseen data?

    python tools/compare_strategies.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.backtester import _timeline, run_backtest          # noqa: E402
from src.config import Config                                # noqa: E402
from src.datafeed import load_history                        # noqa: E402
from src.evaluation import clone_config                      # noqa: E402

OFF = {f"strategies.{s}.enabled": False
       for s in ("momentum", "mean_reversion", "dual_momentum", "trend")}


def cand(**on):
    o = dict(OFF)
    for s in on:
        o[f"strategies.{s}.enabled"] = True
    return o


CANDIDATES = {
    "baseline (mom+mr)":      {"strategies.momentum.enabled": True,
                               "strategies.mean_reversion.enabled": True},
    "dual_momentum":          cand(dual_momentum=True),
    "trend":                  cand(trend=True),
    "dualmom+trend":          cand(dual_momentum=True, trend=True),
    "trend+mr":               cand(trend=True, mean_reversion=True),
    "all4 ensemble":          cand(momentum=True, mean_reversion=True,
                                   dual_momentum=True, trend=True),
}


def bench_return(history, benchmark, start, end):
    df = history.get(benchmark)
    if df is None or df.empty:
        return None
    s = df["close"]
    s = s[(s.index >= start) & (s.index <= end)].dropna()
    return float(s.iloc[-1] / s.iloc[0] - 1) if len(s) > 1 else None


def row(m):
    if "error" in m:
        return f"{'ERR':>8}"
    return (f"ret={m['total_return']*100:+6.1f}% cagr={m['cagr']*100:+5.1f}% "
            f"shp={m['sharpe']:+4.2f} dd={m['max_drawdown']*100:5.1f}% "
            f"2wkNeg={m['pct_2wk_blocks_negative']*100:4.0f}% trd={m['trades']:>4}")


def main():
    cfg = Config.load()
    hist = load_history(cfg.all_symbols, source="cache")
    tl = _timeline(hist, cfg.benchmark)
    first, last = tl[0], tl[-1]
    oos_start = last - pd.Timedelta(days=int(3 * 365.25))
    is_start = first + pd.Timedelta(days=400)

    windows = {
        "IN-SAMPLE (older)": (is_start, oos_start),
        "OUT-OF-SAMPLE (recent 3y)": (oos_start, last),
    }
    for wname, (ws, we) in windows.items():
        print(f"\n================ {wname}  {ws.date()}..{we.date()} ================")
        b = bench_return(hist, cfg.benchmark, ws, we)
        print(f"  benchmark {cfg.benchmark} buy&hold: {b*100:+.1f}%" if b is not None else "")
        for name, ov in CANDIDATES.items():
            c = clone_config(cfg, ov)
            m = run_backtest(c, hist, eval_start=ws, eval_end=we)
            print(f"  {name:<20} {row(m)}")


if __name__ == "__main__":
    main()
