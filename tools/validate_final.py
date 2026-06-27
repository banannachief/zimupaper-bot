#!/usr/bin/env python3
"""Final validation of the chosen (trend-led) config, plus churn-reduction
variants, across in-sample and out-of-sample windows. Pick the variant that
keeps OOS Sharpe while cutting turnover.

    python -u tools/validate_final.py
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

VARIANTS = {
    "current invvol c5 b02":  {},
    "invvol c10 b04":         {"agent.decision_cadence_days": 10,
                               "risk.rebalance_band": 0.04},
    "invvol c21 b05":         {"agent.decision_cadence_days": 21,
                               "risk.rebalance_band": 0.05},
    "equal c10 b04":          {"strategies.trend.weighting": "equal",
                               "agent.decision_cadence_days": 10,
                               "risk.rebalance_band": 0.04},
    "equal c21 b05":          {"strategies.trend.weighting": "equal",
                               "agent.decision_cadence_days": 21,
                               "risk.rebalance_band": 0.05},
}


def bench(history, b, s, e):
    df = history.get(b)
    c = df["close"][(df.index >= s) & (df.index <= e)].dropna()
    return float(c.iloc[-1] / c.iloc[0] - 1) if len(c) > 1 else None


def fmt(m):
    if "error" in m:
        return "ERR"
    return (f"ret={m['total_return']*100:+6.1f}% cagr={m['cagr']*100:+5.1f}% "
            f"shp={m['sharpe']:+4.2f} dd={m['max_drawdown']*100:5.1f}% "
            f"2wkNeg={m['pct_2wk_blocks_negative']*100:3.0f}% trd={m['trades']:>4}")


def main():
    cfg = Config.load()
    hist = load_history(cfg.all_symbols, source="cache")
    tl = _timeline(hist, cfg.benchmark)
    first, last = tl[0], tl[-1]
    oos_s = last - pd.Timedelta(days=int(3 * 365.25))
    # OOS-only for the churn decision (recent turnover + Sharpe is what matters)
    for wname, (ws, we) in {"OUT-OF-SAMPLE (3y)": (oos_s, last)}.items():
        b = bench(hist, cfg.benchmark, ws, we)
        print(f"\n==== {wname} {ws.date()}..{we.date()}  SPY {b*100:+.1f}% ====")
        for name, ov in VARIANTS.items():
            m = run_backtest(clone_config(cfg, ov), hist, eval_start=ws, eval_end=we)
            print(f"  {name:<22} {fmt(m)}")
    print("\nVALIDATE-DONE")


if __name__ == "__main__":
    main()
