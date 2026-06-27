"""Technical indicators — pure functions over pandas Series/DataFrames.

Each works on a price Series (or OHLC DataFrame) and returns a Series aligned
to the input index. Kept dependency-light (numpy/pandas only) and fully unit
tested, because every downstream decision rests on these being correct.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def returns(series: pd.Series, periods: int = 1) -> pd.Series:
    """Simple percentage returns over ``periods`` bars."""
    return series.pct_change(periods)


def log_returns(series: pd.Series) -> pd.Series:
    return np.log(series / series.shift(1))


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI in [0, 100]. Short periods (2-3) are used for mean reversion."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # When there were no losses at all, RSI is 100; no gains -> 0.
    out = out.where(avg_loss != 0.0, 100.0)
    out = out.where(avg_gain != 0.0, out.where(avg_loss == 0.0, 0.0))
    return out


def true_range(df: pd.DataFrame) -> pd.Series:
    """True range from an OHLC frame (columns: high, low, close)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average true range (Wilder smoothing). Used for vol-targeted sizing & stops."""
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def realized_vol(series: pd.Series, window: int = 20, annualize: bool = True) -> pd.Series:
    """Rolling realized volatility of daily returns."""
    r = log_returns(series)
    vol = r.rolling(window, min_periods=window).std()
    if annualize:
        vol = vol * np.sqrt(252.0)
    return vol


def rolling_sharpe(daily_returns: pd.Series, window: int = 20) -> pd.Series:
    """Rolling annualized Sharpe ratio (rf assumed 0)."""
    mean = daily_returns.rolling(window, min_periods=max(2, window // 2)).mean()
    std = daily_returns.rolling(window, min_periods=max(2, window // 2)).std()
    sharpe = (mean / std.replace(0.0, np.nan)) * np.sqrt(252.0)
    return sharpe.fillna(0.0)


def max_drawdown(equity: pd.Series) -> float:
    """Worst peak-to-trough drawdown of an equity curve, as a negative fraction."""
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    return float(dd.min())


def slope(series: pd.Series, window: int = 20) -> pd.Series:
    """Normalized linear-regression slope over a window (per-bar % drift)."""
    def _slope(vals: np.ndarray) -> float:
        if np.any(~np.isfinite(vals)):
            return np.nan
        x = np.arange(len(vals), dtype=float)
        # least-squares slope, normalized by mean level
        b = np.polyfit(x, vals, 1)[0]
        lvl = np.mean(vals)
        return b / lvl if lvl else 0.0

    return series.rolling(window, min_periods=window).apply(_slope, raw=True)
