"""Out-of-sample evaluation & walk-forward optimization.

The whole point: never judge a strategy on data it was tuned on. Parameters are
chosen on a TRAIN window and scored on the next, unseen TEST window. The stitched
sequence of test windows is the honest "what you'd actually have gotten" track
record. Anything that only looks good in-sample is discarded.
"""
from __future__ import annotations

import copy
import itertools

import numpy as np
import pandas as pd

from .backtester import _timeline, run_backtest
from .config import Config
from .indicators import max_drawdown


# --------------------------------------------------------------- config tools
def clone_config(base: Config, overrides: dict) -> Config:
    raw = copy.deepcopy(base.raw)
    for dotted, val in (overrides or {}).items():
        node = raw
        keys = dotted.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = val
    return Config(raw=raw)


def grid_combos(grid: dict[str, list]) -> list[dict]:
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*[grid[k] for k in keys])]


# ------------------------------------------------------------------- scoring
def objective(m: dict) -> float:
    """Maximize: risk-adjusted return, penalized for frequent 2-week losses.

    Aligned with the mandate (steady gains, avoid losing fortnights) rather than
    raw return (which overfits to lucky tails). Guards against blow-ups.
    """
    if not m or "error" in m:
        return -99.0
    sharpe = m.get("sharpe", 0.0) or 0.0
    dd = m.get("max_drawdown", 0.0) or 0.0
    neg2 = m.get("pct_2wk_blocks_negative", 1.0)
    score = sharpe - 1.5 * neg2
    if dd < -0.30:                    # discourage catastrophic drawdowns
        score -= (abs(dd) - 0.30) * 5
    return float(score)


# ------------------------------------------------------------ window helpers
def window_metrics(base: Config, overrides: dict, history: dict,
                   start, end) -> dict:
    cfg = clone_config(base, overrides)
    return run_backtest(cfg, history, eval_start=start, eval_end=end)


def window_returns(base: Config, overrides: dict, history: dict,
                   start, end) -> pd.Series:
    cfg = clone_config(base, overrides)
    _, state = run_backtest(cfg, history, eval_start=start, eval_end=end, return_state=True)
    curve = state.equity_curve
    if len(curve) < 3:
        return pd.Series(dtype=float)
    eq = pd.Series([p["equity"] for p in curve],
                   index=pd.to_datetime([p["t"] for p in curve]))
    if eq.index.tz is not None:
        eq.index = eq.index.tz_localize(None)
    eq = eq[~eq.index.duplicated(keep="last")].sort_index()
    return eq.pct_change().dropna()


# ------------------------------------------------------------- optimization
def grid_search(base: Config, history: dict, grid: dict,
                train_start, train_end) -> tuple[dict, float, list]:
    results = []
    for combo in grid_combos(grid):
        m = window_metrics(base, combo, history, train_start, train_end)
        results.append((combo, objective(m), m))
    results.sort(key=lambda x: x[1], reverse=True)
    best = results[0]
    return best[0], best[1], results


def _metrics_from_returns(rets: pd.Series, weekly_target: float) -> dict:
    if rets is None or len(rets) < 5:
        return {"error": "insufficient OOS data"}
    eq = (1 + rets).cumprod()
    years = max(len(rets) / 252.0, 1e-9)
    total = float(eq.iloc[-1] - 1)
    cagr = float(eq.iloc[-1] ** (1 / years) - 1)
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() else 0.0
    mdd = float(max_drawdown(eq))
    weekly = eq.resample("W").last().pct_change().dropna() if isinstance(
        eq.index, pd.DatetimeIndex) else pd.Series(dtype=float)
    biweek = eq.resample("2W").last().pct_change().dropna() if isinstance(
        eq.index, pd.DatetimeIndex) else pd.Series(dtype=float)
    return {
        "oos_total_return": round(total, 4),
        "oos_cagr": round(cagr, 4),
        "oos_sharpe": round(sharpe, 2),
        "oos_max_drawdown": round(mdd, 4),
        "oos_pct_weeks_hit_target": round(float((weekly >= weekly_target).mean()) if len(weekly) else 0.0, 3),
        "oos_pct_weeks_negative": round(float((weekly < 0).mean()) if len(weekly) else 0.0, 3),
        "oos_pct_2wk_negative": round(float((biweek < 0).mean()) if len(biweek) else 0.0, 3),
        "oos_days": len(rets),
    }


def walk_forward(base: Config, history: dict, grid: dict, *,
                 train_years: float = 4.0, test_years: float = 1.0,
                 verbose: bool = True) -> dict:
    """Rolling train→test. Returns stitched OOS metrics + per-window detail."""
    timeline = _timeline(history, base.benchmark)
    if len(timeline) < 50:
        return {"error": "not enough history"}
    first, last = timeline[0], timeline[-1]
    train_td = pd.Timedelta(days=int(train_years * 365.25))
    test_td = pd.Timedelta(days=int(test_years * 365.25))

    windows = []
    test_start = first + train_td
    while test_start < last:
        test_end = min(test_start + test_td, last)
        windows.append((test_start - train_td, test_start, test_end))
        test_start = test_end + pd.Timedelta(days=1)

    oos_rets = []
    detail = []
    for (tr_s, te_s, te_e) in windows:
        best, score, _ = grid_search(base, history, grid, tr_s, te_s)
        rets = window_returns(base, best, history, te_s, te_e)
        m = _metrics_from_returns(rets, base.weekly_gain)
        oos_rets.append(rets)
        detail.append({
            "train": f"{tr_s.date()}..{te_s.date()}",
            "test": f"{te_s.date()}..{te_e.date()}",
            "best_params": best, "train_score": round(score, 3),
            "oos": m,
        })
        if verbose:
            print(f"  test {te_s.date()}..{te_e.date()}  "
                  f"ret={m.get('oos_total_return')} sharpe={m.get('oos_sharpe')} "
                  f"dd={m.get('oos_max_drawdown')}  params={best}")

    stitched = pd.concat(oos_rets).sort_index() if oos_rets else pd.Series(dtype=float)
    agg = _metrics_from_returns(stitched, base.weekly_gain)
    return {"oos_aggregate": agg, "windows": detail, "n_windows": len(windows)}


def walk_forward_candidates(base: Config, history: dict,
                            candidates: dict[str, dict], *,
                            train_years: float = 4.0, test_years: float = 1.0,
                            verbose: bool = True) -> dict:
    """Like walk_forward, but the choice each window is *which candidate config*
    (strategy combo), picked by train-window objective, scored OOS on the next.
    Answers: does picking the best-looking strategy set generalize forward?
    """
    timeline = _timeline(history, base.benchmark)
    if len(timeline) < 50:
        return {"error": "not enough history"}
    first, last = timeline[0], timeline[-1]
    train_td = pd.Timedelta(days=int(train_years * 365.25))
    test_td = pd.Timedelta(days=int(test_years * 365.25))

    windows = []
    ts = first + train_td
    while ts < last:
        te = min(ts + test_td, last)
        windows.append((ts - train_td, ts, te))
        ts = te + pd.Timedelta(days=1)

    oos_rets, detail, picks = [], [], []
    for (tr_s, te_s, te_e) in windows:
        scored = []
        for name, ov in candidates.items():
            m = window_metrics(base, ov, history, tr_s, te_s)
            scored.append((name, objective(m)))
        scored.sort(key=lambda x: x[1], reverse=True)
        best_name = scored[0][0]
        picks.append(best_name)
        rets = window_returns(base, candidates[best_name], history, te_s, te_e)
        m = _metrics_from_returns(rets, base.weekly_gain)
        oos_rets.append(rets)
        detail.append({"test": f"{te_s.date()}..{te_e.date()}",
                       "picked": best_name, "oos": m})
        if verbose:
            print(f"  {te_s.date()}..{te_e.date()} picked={best_name:<18} "
                  f"oos_ret={m.get('oos_total_return')} sharpe={m.get('oos_sharpe')}")

    stitched = pd.concat(oos_rets).sort_index() if oos_rets else pd.Series(dtype=float)
    return {"oos_aggregate": _metrics_from_returns(stitched, base.weekly_gain),
            "windows": detail, "picks": picks, "n_windows": len(windows)}


def holdout_eval(base: Config, history: dict, grid: dict, *,
                 holdout_years: float = 2.0) -> dict:
    """Single split: tune on everything before the holdout, report on the holdout."""
    timeline = _timeline(history, base.benchmark)
    last = timeline[-1]
    split = last - pd.Timedelta(days=int(holdout_years * 365.25))
    first = timeline[0]
    best, score, results = grid_search(base, history, grid, first, split)
    is_m = window_metrics(base, best, history, first, split)
    oos_m = window_metrics(base, best, history, split, last)
    return {"split": str(split.date()), "best_params": best,
            "in_sample": is_m, "out_of_sample": oos_m,
            "top5": [(c, round(s, 3)) for c, s, _ in results[:5]]}
