"""Safety/hardening tests: the bot must NOT do dangerous things on bad input."""
import numpy as np
import pandas as pd

from src.config import Config
from src.engine import _data_too_thin
from src.strategies.trend import TrendStrategy

CONTEXT = {"cash_asset": "BIL", "benchmark": "SPY"}


def _ohlc(n=300, slope=0.0015, seed=1):
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(seed)
    close = pd.Series(100 * np.exp(np.cumsum(np.full(n, slope) + rng.normal(0, 0.006, n))),
                      index=idx)
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": 1e6}, index=idx)


def test_data_guard_blocks_trading_on_empty_feed():
    cfg = Config.load()
    # totally empty feed -> too thin (must NOT trade; would liquidate otherwise)
    assert _data_too_thin({}, cfg, None) is True
    # missing benchmark -> too thin
    df = _ohlc()
    assert _data_too_thin({s: df for s in cfg.universe}, cfg, None) is True


def test_data_guard_allows_trading_with_full_feed():
    cfg = Config.load()
    df = _ohlc()
    data = {s: df for s in cfg.all_symbols}
    assert _data_too_thin(data, cfg, df) is False


def test_trend_equal_weighting_is_uniform():
    uni = ["AAA", "BBB", "CCC", "DDD"]
    hist = {s: _ohlc(slope=0.0015, seed=i) for i, s in enumerate(uni)}
    hist["BIL"] = _ohlc(slope=0.0001, seed=9)
    w = TrendStrategy({"weighting": "equal"}).target_weights(hist, uni, CONTEXT)
    assert w
    vals = list(w.values())
    assert all(abs(v - vals[0]) < 1e-9 for v in vals)   # all equal
    assert abs(sum(vals) - 1.0) < 1e-6
