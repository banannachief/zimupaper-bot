import numpy as np
import pandas as pd

from src.indicators import atr, max_drawdown, rsi, sma, realized_vol


def test_sma_basic():
    s = pd.Series(range(1, 11), dtype=float)
    assert sma(s, 3).iloc[-1] == (8 + 9 + 10) / 3


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.linspace(10, 50, 60))
    down = pd.Series(np.linspace(50, 10, 60))
    r_up = rsi(up, 14).iloc[-1]
    r_down = rsi(down, 14).iloc[-1]
    assert 0 <= r_down <= 100 and 0 <= r_up <= 100
    assert r_up > 70          # steady uptrend -> high RSI
    assert r_down < 30        # steady downtrend -> low RSI


def test_atr_positive():
    n = 50
    df = pd.DataFrame({
        "high": np.linspace(101, 150, n),
        "low": np.linspace(99, 148, n),
        "close": np.linspace(100, 149, n),
    })
    a = atr(df, 14).iloc[-1]
    assert a > 0


def test_max_drawdown():
    assert max_drawdown(pd.Series([1, 2, 3, 4])) == 0.0
    assert abs(max_drawdown(pd.Series([100, 50])) - (-0.5)) < 1e-9


def test_realized_vol_nonnegative():
    s = pd.Series(100 * np.cumprod(1 + np.random.default_rng(0).normal(0, 0.01, 100)))
    v = realized_vol(s, 20).iloc[-1]
    assert v >= 0
