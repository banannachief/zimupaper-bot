#!/usr/bin/env python3
"""Download real daily history ONCE and cache it to data/cache/*.parquet.

Robust against yfinance's rate-limits/cache-locks: per-symbol retries with
backoff, batch first then fill gaps individually. Run:

    python tools/build_data_cache.py            # live universe + research set
    python tools/build_data_cache.py --years 12

After this, backtests/optimization read from the local cache (fast, offline).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CACHE = ROOT / "data" / "cache"

# Live universe + an extended research set (gives cross-sectional models more breadth).
LIVE = ["SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLV", "XLE", "XLY", "XLP",
        "GLD", "TLT", "BIL"]
RESEARCH_EXTRA = ["VTI", "VEA", "VWO", "EFA", "EEM", "AGG", "LQD", "HYG", "IEF",
                  "SHY", "TIP", "XLB", "XLI", "XLU", "XLRE", "XLC", "SMH", "IBB",
                  "VNQ", "DBC", "SLV", "UUP", "MTUM", "QUAL", "USMV", "VLUE"]
COLUMNS = ["open", "high", "low", "close", "volume"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)
    df = df[[c for c in COLUMNS if c in df.columns]].dropna()
    return df


def fetch_one(sym: str, years: int, tries: int = 4) -> pd.DataFrame | None:
    import yfinance as yf
    for attempt in range(tries):
        try:
            df = yf.download(sym, period=f"{years}y", interval="1d",
                             auto_adjust=True, progress=False, threads=False)
            if df is not None and len(df) > 60:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return _clean(df)
        except Exception as e:
            print(f"  {sym} attempt {attempt+1} failed: {str(e)[:80]}")
        time.sleep(2 + attempt * 3)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=12)
    ap.add_argument("--live-only", action="store_true")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    symbols = LIVE if args.live_only else LIVE + RESEARCH_EXTRA
    print(f"Caching {len(symbols)} symbols, ~{args.years}y, into {CACHE}")

    ok, fail = [], []
    for i, sym in enumerate(symbols, 1):
        path = CACHE / f"{sym}.parquet"
        if path.exists():
            try:
                existing = pd.read_parquet(path)
                if len(existing) > 200:
                    print(f"[{i}/{len(symbols)}] {sym}: cached ({len(existing)} rows)")
                    ok.append(sym)
                    continue
            except Exception:
                pass
        df = fetch_one(sym, args.years)
        if df is not None and len(df) > 60:
            df.to_parquet(path)
            print(f"[{i}/{len(symbols)}] {sym}: {len(df)} rows -> cached")
            ok.append(sym)
        else:
            print(f"[{i}/{len(symbols)}] {sym}: FAILED")
            fail.append(sym)
        time.sleep(1.0)

    print(f"\nDone. cached={len(ok)} failed={len(fail)} {fail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
