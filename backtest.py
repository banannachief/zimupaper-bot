#!/usr/bin/env python3
"""Backtest the strategy + agent + risk stack on historical data.

    python backtest.py                       # real data (yfinance) if available, else synthetic
    python backtest.py --source synthetic    # force offline synthetic data
    python backtest.py --source yfinance --years 4

The backtest runs the EXACT same engine code path as live trading, so good
backtest numbers mean the live logic is sound (not that the future is known).
"""
from __future__ import annotations

import argparse
import json

from src.backtester import run_backtest
from src.config import Config
from src.datafeed import load_history


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--source", default="auto",
                    choices=["auto", "cache", "yfinance", "synthetic"])
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--cash", type=float, default=100_000.0)
    ap.add_argument("--json", action="store_true", help="print raw JSON only")
    args = ap.parse_args()

    config = Config.load(args.config)
    days = args.years * 252
    print(f"Loading ~{args.years}y of history for {len(config.all_symbols)} symbols "
          f"(source={args.source})...")
    history = load_history(config.all_symbols, days=days, source=args.source)
    got = {s: len(df) for s, df in history.items() if len(df)}
    print(f"Loaded {len(got)}/{len(config.all_symbols)} symbols.\n")

    res = run_backtest(config, history, starting_cash=args.cash)
    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    if "error" in res:
        print("Backtest error:", res)
        return 1

    def pc(x):
        return f"{x*100:+.2f}%" if x is not None else "n/a"

    print("=" * 56)
    print(f"  BACKTEST  {res['start']} -> {res['end']}  ({res['days']} days)")
    print("=" * 56)
    print(f"  Start equity        ${res['start_equity']:>12,.0f}")
    print(f"  End equity          ${res['end_equity']:>12,.0f}")
    print(f"  Total return        {pc(res['total_return']):>13}")
    print(f"  CAGR                {pc(res['cagr']):>13}")
    print(f"  Benchmark ({config.benchmark}) ret  {pc(res['benchmark_return']):>9}")
    print(f"  Annualized vol      {pc(res['ann_vol']):>13}")
    print(f"  Sharpe              {res['sharpe']:>13.2f}")
    print(f"  Max drawdown        {pc(res['max_drawdown']):>13}")
    print("-" * 56)
    print(f"  Weekly target       {pc(res['weekly_target']):>13}")
    print(f"  Weeks               {res['weeks']:>13}")
    print(f"  % weeks hit target  {res['pct_weeks_hit_target']*100:>12.1f}%")
    print(f"  % weeks negative    {res['pct_weeks_negative']*100:>12.1f}%")
    print(f"  Avg weekly return   {pc(res['avg_weekly_return']):>13}")
    print(f"  % 2-wk blocks neg   {res['pct_2wk_blocks_negative']*100:>12.1f}%")
    print(f"  Total trades        {res['trades']:>13}")
    print("=" * 56)
    print("  NOTE: synthetic data validates the machinery only. Use --source")
    print("  yfinance for real history, and remember past != future.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
