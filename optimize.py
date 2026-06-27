#!/usr/bin/env python3
"""Out-of-sample optimizer / validator.

    python optimize.py --mode holdout       # tune on history, report on held-out recent years
    python optimize.py --mode walkforward   # rolling train->test (most honest)

Only OOS (out-of-sample) numbers are trustworthy. In-sample numbers are shown
only to expose overfitting (big IS-vs-OOS gap = overfit).
"""
from __future__ import annotations

import argparse
import json

from src.config import Config
from src.datafeed import load_history
from src.evaluation import holdout_eval, walk_forward

# Modest parameter grid — the knobs most likely to matter, kept small so
# walk-forward stays tractable. Structural ideas are explored separately.
DEFAULT_GRID = {
    "strategies.momentum.slow": [80, 120, 160],
    "strategies.momentum.top_n": [3, 5],
    "agent.score_window": [15, 30],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--mode", default="holdout", choices=["holdout", "walkforward"])
    ap.add_argument("--source", default="cache")
    ap.add_argument("--holdout-years", type=float, default=3.0)
    ap.add_argument("--train-years", type=float, default=5.0)
    ap.add_argument("--test-years", type=float, default=1.5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    config = Config.load(args.config)
    hist = load_history(config.all_symbols, source=args.source)
    got = sum(1 for s in config.all_symbols if s in hist and len(hist[s]) > 60)
    print(f"Loaded {got}/{len(config.all_symbols)} symbols from {args.source}.\n")

    if args.mode == "holdout":
        res = holdout_eval(config, hist, DEFAULT_GRID, holdout_years=args.holdout_years)
        if args.json:
            print(json.dumps(res, indent=2, default=str)); return 0
        print(f"Split at {res['split']}  (tune before, test after)")
        print(f"Best params: {res['best_params']}")
        is_m, oos = res["in_sample"], res["out_of_sample"]
        print("\n               IN-SAMPLE     OUT-OF-SAMPLE")
        for k, lab in [("total_return", "Total return"), ("cagr", "CAGR"),
                       ("sharpe", "Sharpe"), ("max_drawdown", "Max drawdown"),
                       ("pct_2wk_blocks_negative", "% 2wk negative")]:
            iv, ov = is_m.get(k), oos.get(k)
            print(f"  {lab:<14} {str(iv):>10}    {str(ov):>10}")
        print(f"\n  Benchmark OOS would be SPY buy&hold over the same window.")
    else:
        res = walk_forward(config, hist, DEFAULT_GRID,
                           train_years=args.train_years, test_years=args.test_years)
        if args.json:
            print(json.dumps(res, indent=2, default=str)); return 0
        print(f"\nWalk-forward: {res.get('n_windows')} windows")
        agg = res.get("oos_aggregate", {})
        print("\n=== STITCHED OUT-OF-SAMPLE (honest) ===")
        for k, v in agg.items():
            print(f"  {k:<26} {v}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
