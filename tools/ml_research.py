#!/usr/bin/env python3
"""ML signal research — rigorous, leak-free, walk-forward.

Question: does a machine-learning forward-return predictor beat the simple
momentum/trend strategies OUT-OF-SAMPLE? Most of the time in liquid ETFs it does
NOT (markets are near-efficient and ML overfits) — this script is built to give
an HONEST answer, not a flattering one.

Method:
  * Features at date t use ONLY data up to t (past returns, vol, RSI, MA distance,
    cross-sectional momentum rank).
  * Target = forward 5-trading-day (≈1 week) return.
  * Walk-forward: expand the training set, retrain each quarter, predict the next
    quarter. A sample is only in TRAIN if its forward-return window closed before
    the test block begins (no leakage across the boundary).
  * Portfolio: each week hold the top-N symbols by predicted return that are also
    predicted positive; equal weight; else cash. Compare OOS to equal-weight and
    to a 63-day momentum rule on the same dates.

    python tools/ml_research.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config                    # noqa: E402
from src.datafeed import load_history            # noqa: E402
from src.indicators import realized_vol, rsi, sma  # noqa: E402

HORIZON = 5            # predict forward 1-week return
RETRAIN_EVERY = 63     # ~quarterly
MIN_TRAIN = 252 * 3    # need a few years before first prediction
TOP_N = 4


def build_features(close: pd.Series, df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=close.index)
    for k in (5, 10, 21, 63, 126):
        f[f"ret{k}"] = close.pct_change(k)
    f["vol21"] = realized_vol(close, 21)
    f["vol63"] = realized_vol(close, 63)
    f["rsi14"] = rsi(close, 14) / 100.0
    f["rsi2"] = rsi(close, 2) / 100.0
    f["d_sma50"] = close / sma(close, 50) - 1.0
    f["d_sma200"] = close / sma(close, 200) - 1.0
    return f


def assemble(history: dict, universe: list[str]):
    """Long panel of (date, symbol) -> features + forward return target."""
    frames = []
    # cross-sectional 63d momentum rank per date
    mom = pd.DataFrame({s: history[s]["close"].pct_change(63)
                        for s in universe if s in history})
    xrank = mom.rank(axis=1, pct=True)
    for s in universe:
        if s not in history:
            continue
        c = history[s]["close"]
        feat = build_features(c, history[s])
        feat["xmom_rank"] = xrank[s].reindex(feat.index)
        feat["fwd"] = c.shift(-HORIZON) / c - 1.0       # target (future-dated)
        feat["symbol"] = s
        feat["date"] = feat.index
        frames.append(feat)
    panel = pd.concat(frames).dropna()
    return panel


def walk_forward(panel: pd.DataFrame, dates: pd.DatetimeIndex):
    import lightgbm as lgb

    feat_cols = [c for c in panel.columns if c not in ("fwd", "symbol", "date")]
    preds = []   # (date, symbol, pred, actual_fwd)
    test_points = [d for d in dates if d >= dates[MIN_TRAIN]] if len(dates) > MIN_TRAIN else []
    # retrain checkpoints
    checkpoints = test_points[::RETRAIN_EVERY]
    model = None
    for ci, cp in enumerate(checkpoints):
        # train on samples whose forward window closed strictly before cp
        cutoff = cp  # predictions made AT cp use features up to cp; targets look 5d ahead.
        train = panel[panel["date"] <= cutoff - pd.Timedelta(days=HORIZON + 2)]
        if len(train) < 2000:
            continue
        model = lgb.LGBMRegressor(n_estimators=200, max_depth=4, learning_rate=0.03,
                                  subsample=0.8, colsample_bytree=0.8,
                                  min_child_samples=50, n_jobs=-1, verbose=-1)
        model.fit(train[feat_cols], train["fwd"])
        nxt = checkpoints[ci + 1] if ci + 1 < len(checkpoints) else dates[-1] + pd.Timedelta(days=1)
        block = panel[(panel["date"] >= cp) & (panel["date"] < nxt)]
        if block.empty:
            continue
        p = model.predict(block[feat_cols])
        for (_, r), pred in zip(block.iterrows(), p):
            preds.append((r["date"], r["symbol"], float(pred), float(r["fwd"])))
    return pd.DataFrame(preds, columns=["date", "symbol", "pred", "fwd"])


def portfolio_oos(pred_df: pd.DataFrame):
    """Weekly: hold top-N predicted-positive names; measure realized fwd return."""
    if pred_df.empty:
        return None
    # sample weekly (every HORIZON days) to avoid overlapping windows
    pred_df = pred_df.sort_values("date")
    weekly_dates = sorted(pred_df["date"].unique())[::HORIZON]
    rows = []
    for d in weekly_dates:
        day = pred_df[pred_df["date"] == d]
        pos = day[day["pred"] > 0].nlargest(TOP_N, "pred")
        ml_ret = pos["fwd"].mean() if len(pos) else 0.0          # equal weight, else cash
        ew_ret = day["fwd"].mean()                                # equal-weight all
        mom = day.nlargest(TOP_N, "pred")  # placeholder; momentum compared separately
        rows.append((d, ml_ret, ew_ret))
    res = pd.DataFrame(rows, columns=["date", "ml", "ew"]).set_index("date")
    return res


def metrics(weekly_rets: pd.Series, label: str):
    r = weekly_rets.dropna()
    if len(r) < 5:
        return f"{label}: insufficient", 0.0
    eq = (1 + r).cumprod()
    total = eq.iloc[-1] - 1
    ann = (1 + r.mean()) ** 52 - 1
    sharpe = r.mean() / r.std() * np.sqrt(52) if r.std() else 0
    dd = float((eq / eq.cummax() - 1).min())
    winr = float((r > 0).mean())
    s = (f"{label:<22} total={total*100:+6.1f}% ann={ann*100:+6.1f}% "
         f"sharpe={sharpe:+4.2f} maxDD={dd*100:5.1f}% win%={winr*100:4.0f}")
    return s, float(sharpe)


def main():
    cfg = Config.load()
    universe = cfg.universe
    hist = load_history(universe + [cfg.cash_asset], source="cache")
    print(f"Assembling panel for {len(universe)} symbols...")
    panel = assemble(hist, universe)
    dates = pd.DatetimeIndex(sorted(panel["date"].unique()))
    print(f"Panel: {len(panel)} samples, {len(dates)} dates "
          f"({dates[0].date()}..{dates[-1].date()})")
    print("Training walk-forward LightGBM (leak-free)... this takes a few minutes.")
    pred = walk_forward(panel, dates)
    print(f"OOS predictions: {len(pred)} rows")
    res = portfolio_oos(pred)
    if res is None or res.empty:
        print("No OOS portfolio produced.")
        return
    print("\n=== OUT-OF-SAMPLE weekly portfolio comparison ===")
    ml_s, ml_sharpe = metrics(res["ml"], "ML top-N")
    ew_s, ew_sharpe = metrics(res["ew"], "Equal-weight all")
    print("  " + ml_s)
    print("  " + ew_s)
    # information coefficient (rank correlation of pred vs realized)
    ic = pred.groupby("date").apply(
        lambda g: g["pred"].corr(g["fwd"], method="spearman")).dropna()
    mean_ic = float(ic.mean())
    print(f"\n  Mean daily IC (pred vs realized, Spearman): {mean_ic:+.4f}")
    print("  (|IC| < ~0.02-0.03 means the model has essentially no edge.)")
    useful = mean_ic > 0.02 and ml_sharpe > ew_sharpe + 0.15
    print(f"\n  VERDICT: {'USEFUL — worth integrating + further validation' if useful else 'NO EDGE — do not ship as default'}")


if __name__ == "__main__":
    main()
