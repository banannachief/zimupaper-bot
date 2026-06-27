"""Historical data for backtests.

Tries yfinance first (real history). If it's unavailable or offline, falls back
to a deterministic synthetic generator so the backtester and tests ALWAYS run.
Synthetic data is clearly not real — it exists to validate the machinery, never
to claim performance.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def load_cached(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Load whatever symbols are present in the local parquet cache."""
    out: dict[str, pd.DataFrame] = {}
    for s in symbols:
        p = CACHE_DIR / f"{s}.parquet"
        if p.exists():
            try:
                df = pd.read_parquet(p)
                if not df.empty:
                    out[s] = df[[c for c in COLUMNS if c in df.columns]]
            except Exception:
                pass
    return out


def synthetic_history(symbols: list[str], n: int = 500, seed: int = 42,
                      start: str = "2023-01-02") -> dict[str, pd.DataFrame]:
    """Deterministic GBM-ish OHLCV per symbol. Distinct trend/vol per symbol."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=n)
    out: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(symbols):
        drift = 0.0002 + 0.00015 * np.sin(i)        # mild, symbol-specific drift
        vol = 0.008 + 0.004 * ((i * 7) % 5) / 4.0    # 0.8%..1.2% daily vol
        shocks = rng.normal(drift, vol, size=n)
        # add a couple of regime shifts so strategies have something to chew on
        shocks[n // 3: n // 3 + 20] -= vol * 2.0
        shocks[2 * n // 3: 2 * n // 3 + 15] += vol * 1.5
        price = 100.0 * np.exp(np.cumsum(shocks))
        close = pd.Series(price, index=idx)
        intraday = np.abs(rng.normal(0, vol, size=n))
        high = close * (1 + intraday)
        low = close * (1 - intraday)
        open_ = close.shift(1).fillna(close.iloc[0])
        vol_series = pd.Series(rng.integers(1_000_000, 5_000_000, size=n), index=idx)
        out[sym] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol_series}
        )[COLUMNS]
    return out


def yfinance_history(symbols: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    """Real daily history via yfinance. Raises on failure so callers can fall back."""
    import yfinance as yf  # local import; optional dependency

    data = yf.download(symbols, period=period, interval="1d",
                       auto_adjust=True, progress=False, group_by="ticker")
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = data[sym] if len(symbols) > 1 else data
            df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
        except Exception:
            continue
        if not df.empty:
            out[sym] = df
    if not out:
        raise RuntimeError("yfinance returned no data")
    return out


def load_history(symbols: list[str], days: int = 500,
                 source: str = "auto", seed: int = 42) -> dict[str, pd.DataFrame]:
    """Load history. ``source``: auto | cache | yfinance | synthetic.

    'auto' prefers the local parquet cache (built by tools/build_data_cache.py),
    then yfinance, then deterministic synthetic data so it always returns.
    """
    if source in ("auto", "cache"):
        cached = load_cached(symbols)
        if cached and (source == "cache" or all(s in cached for s in symbols)):
            return cached
        if source == "cache":
            return cached
    if source in ("auto", "yfinance"):
        try:
            years = max(1, int(np.ceil(days / 252)) + 1)
            hist = yfinance_history(symbols, period=f"{years}y")
            if all(len(hist.get(s, [])) >= 60 for s in symbols):
                return hist
            if source == "yfinance":
                return hist
        except Exception:
            if source == "yfinance":
                raise
    return synthetic_history(symbols, n=max(days, 300), seed=seed)
