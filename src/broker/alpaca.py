"""Alpaca broker adapter over the plain REST API (no SDK dependency).

Works identically for paper and live — the only difference is the base URL,
which comes from the ALPACA_BASE_URL secret (paper by default).

Free-tier notes:
  * Trading API: paper-api.alpaca.markets  (live: api.alpaca.markets)
  * Market data: data.alpaca.markets, IEX feed (free). Daily bars are fine.
"""
from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests

from .base import Account, Broker, OrderResult, Position

DATA_URL = "https://data.alpaca.markets"
_RETRY_STATUS = {429, 500, 502, 503, 504}


class AlpacaBroker(Broker):
    def __init__(self, secrets, *, timeout: int = 20):
        self.base = secrets.alpaca_base_url.rstrip("/")
        self.timeout = timeout
        self._headers = {
            "APCA-API-KEY-ID": secrets.alpaca_key,
            "APCA-API-SECRET-KEY": secrets.alpaca_secret,
            "accept": "application/json",
        }

    # ---------------------------------------------------------------- http
    def _request(self, method: str, url: str, *, params=None, json=None,
                 retries: int = 3) -> requests.Response:
        last = None
        for attempt in range(retries):
            try:
                r = requests.request(method, url, headers=self._headers,
                                     params=params, json=json, timeout=self.timeout)
                if r.status_code in _RETRY_STATUS:
                    last = requests.HTTPError(f"{r.status_code}", response=r)
                    time.sleep(1.5 * (attempt + 1))
                    continue
                return r
            except (requests.ConnectionError, requests.Timeout) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        if last:
            raise last
        raise RuntimeError("request failed")

    def _get(self, url: str, params: dict | None = None) -> Any:
        r = self._request("GET", url, params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, url: str, payload: dict) -> Any:
        r = self._request("POST", url, json=payload)
        r.raise_for_status()
        return r.json()

    def _delete(self, url: str) -> Any:
        r = self._request("DELETE", url)
        if r.status_code not in (200, 207):
            r.raise_for_status()
        return r.json() if r.text else {}

    # ------------------------------------------------------------- account
    def get_account(self) -> Account:
        a = self._get(f"{self.base}/v2/account")
        return Account(
            equity=float(a["equity"]),
            cash=float(a["cash"]),
            buying_power=float(a["buying_power"]),
            last_equity=float(a.get("last_equity", a["equity"])),
        )

    def get_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for p in self._get(f"{self.base}/v2/positions"):
            out[p["symbol"]] = Position(
                symbol=p["symbol"],
                qty=float(p["qty"]),
                avg_entry_price=float(p["avg_entry_price"]),
                current_price=float(p.get("current_price", p["avg_entry_price"])),
            )
        return out

    def is_market_open(self) -> bool:
        return bool(self._get(f"{self.base}/v2/clock").get("is_open", False))

    # ---------------------------------------------------------------- data
    def get_bars(self, symbols: list[str], timeframe: str = "1Day",
                 limit: int = 320) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        out: dict[str, list] = {s: [] for s in symbols}
        params = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "limit": 10000,
            "adjustment": "all",
            "feed": "iex",
        }
        page_token = None
        # We want the most recent `limit` bars; the API returns oldest->newest
        # within the requested window. Pull a generous window then trim.
        start = (pd.Timestamp.utcnow() - pd.Timedelta(days=int(limit * 2 + 40))).strftime(
            "%Y-%m-%d"
        )
        params["start"] = start
        for _ in range(20):  # pagination safety bound
            if page_token:
                params["page_token"] = page_token
            data = self._get(f"{DATA_URL}/v2/stocks/bars", params=params)
            bars = data.get("bars") or {}
            for sym, rows in bars.items():
                out.setdefault(sym, []).extend(rows)
            page_token = data.get("next_page_token")
            if not page_token:
                break
            time.sleep(0.1)
        frames: dict[str, pd.DataFrame] = {}
        for sym, rows in out.items():
            if not rows:
                frames[sym] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                continue
            df = pd.DataFrame(rows)
            df["t"] = pd.to_datetime(df["t"])
            df = df.set_index("t").sort_index()
            df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                                    "c": "close", "v": "volume"})
            frames[sym] = df[["open", "high", "low", "close", "volume"]].tail(limit)
        return frames

    # -------------------------------------------------------------- orders
    def submit_order(self, symbol: str, side: str, *, qty: float | None = None,
                     notional: float | None = None) -> OrderResult:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        if notional is not None:
            payload["notional"] = round(float(notional), 2)
        elif qty is not None:
            payload["qty"] = str(round(float(qty), 6))
        else:
            return OrderResult(symbol, side, 0.0, 0.0, ok=False, note="no qty/notional")
        try:
            o = self._post(f"{self.base}/v2/orders", payload)
            return OrderResult(
                symbol=symbol, side=side,
                filled_qty=float(o.get("filled_qty") or 0.0),
                avg_price=float(o.get("filled_avg_price") or 0.0),
                ok=True, note=o.get("status", "submitted"),
            )
        except requests.HTTPError as e:
            body = getattr(e.response, "text", "")
            return OrderResult(symbol, side, 0.0, 0.0, ok=False, note=f"{e} {body[:160]}")

    def close_position(self, symbol: str) -> OrderResult:
        try:
            self._delete(f"{self.base}/v2/positions/{symbol}")
            return OrderResult(symbol, "sell", 0.0, 0.0, ok=True, note="closed")
        except requests.HTTPError as e:
            return OrderResult(symbol, "sell", 0.0, 0.0, ok=False, note=str(e))

    def close_all(self) -> list[OrderResult]:
        try:
            self._delete(f"{self.base}/v2/positions")
            return [OrderResult("ALL", "sell", 0.0, 0.0, ok=True, note="closed all")]
        except requests.HTTPError as e:
            return [OrderResult("ALL", "sell", 0.0, 0.0, ok=False, note=str(e))]
