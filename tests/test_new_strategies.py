import numpy as np
import pandas as pd

from src.strategies.dual_momentum import DualMomentumStrategy
from src.strategies.trend import TrendStrategy

CONTEXT = {"cash_asset": "BIL", "benchmark": "SPY"}
UNIVERSE = ["AAA", "BBB", "CCC", "DDD"]


def _ohlc(close: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": 1_000_000}, index=close.index)


def _trending(n=300, slope=0.001, start=100.0, seed=0):
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(seed)
    steps = np.full(n, slope) + rng.normal(0, 0.006, n)   # drift + realistic noise
    return pd.Series(start * np.exp(np.cumsum(steps)), index=idx)


def _falling(n=300):
    return _trending(n, slope=-0.001)


def test_dual_momentum_picks_uptrenders_over_cash():
    hist = {
        "AAA": _ohlc(_trending(slope=0.002)),
        "BBB": _ohlc(_trending(slope=0.0015)),
        "CCC": _ohlc(_falling()),
        "DDD": _ohlc(_falling()),
        "BIL": _ohlc(_trending(slope=0.00005)),   # flat-ish cash
    }
    w = DualMomentumStrategy({"lookback": 120, "top_n": 2}).target_weights(
        hist, UNIVERSE, CONTEXT)
    assert set(w) <= {"AAA", "BBB"}            # only uptrenders, beating cash
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_dual_momentum_goes_to_cash_when_all_falling():
    hist = {s: _ohlc(_falling()) for s in UNIVERSE}
    hist["BIL"] = _ohlc(_trending(slope=0.0001))
    w = DualMomentumStrategy({"lookback": 120, "top_n": 2}).target_weights(
        hist, UNIVERSE, CONTEXT)
    assert w == {}                              # nothing beats cash -> flat


def test_trend_weights_sum_to_one_when_trending():
    hist = {s: _ohlc(_trending(slope=0.0015)) for s in UNIVERSE}
    hist["BIL"] = _ohlc(_trending(slope=0.0001))
    w = TrendStrategy({"fast": 50, "slow": 200}).target_weights(hist, UNIVERSE, CONTEXT)
    assert w and abs(sum(w.values()) - 1.0) < 1e-6
    assert all(v >= 0 for v in w.values())


def test_trend_empty_when_downtrend():
    hist = {s: _ohlc(_falling()) for s in UNIVERSE}
    hist["BIL"] = _ohlc(_trending(slope=0.0001))
    w = TrendStrategy({"fast": 50, "slow": 200}).target_weights(hist, UNIVERSE, CONTEXT)
    assert w == {}
