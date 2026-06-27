"""Offline simulation broker.

Holds a cash + positions ledger and fills market orders at a "current price"
that the driver (backtester or test) sets each step. No network, no keys —
this is what lets the entire strategy/agent/risk stack be validated and unit
tested deterministically before a single real order is sent.
"""
from __future__ import annotations

import pandas as pd

from .base import Account, Broker, OrderResult, Position


class SimBroker(Broker):
    def __init__(self, starting_cash: float = 100_000.0,
                 commission_bps: float = 0.0, slippage_bps: float = 1.0):
        self.cash = float(starting_cash)
        self._qty: dict[str, float] = {}
        self._avg: dict[str, float] = {}
        self._prices: dict[str, float] = {}
        self._last_equity = float(starting_cash)
        self._history: dict[str, pd.DataFrame] = {}
        self._as_of: pd.Timestamp | None = None
        self.market_open = True
        self.commission = commission_bps / 1e4
        self.slippage = slippage_bps / 1e4

    # ------------------------------------------------------ driver helpers
    def set_history(self, history: dict[str, pd.DataFrame]) -> None:
        self._history = history

    def set_as_of(self, ts) -> None:
        self._as_of = pd.Timestamp(ts)

    def set_prices(self, prices: dict[str, float], snapshot_prev: bool = True) -> None:
        if snapshot_prev and self._prices:
            self._last_equity = self._equity_with(self._prices)
        self._prices.update(prices)

    def _equity_with(self, prices: dict[str, float]) -> float:
        val = self.cash
        for sym, q in self._qty.items():
            if q:
                val += q * prices.get(sym, self._avg.get(sym, 0.0))
        return val

    # ------------------------------------------------------------ Broker API
    def get_account(self) -> Account:
        eq = self._equity_with(self._prices)
        return Account(equity=eq, cash=self.cash, buying_power=self.cash,
                       last_equity=self._last_equity or eq)

    def get_positions(self) -> dict[str, Position]:
        out = {}
        for sym, q in self._qty.items():
            if abs(q) < 1e-9:
                continue
            out[sym] = Position(symbol=sym, qty=q, avg_entry_price=self._avg.get(sym, 0.0),
                                current_price=self._prices.get(sym, self._avg.get(sym, 0.0)))
        return out

    def get_bars(self, symbols, timeframe="1Day", limit=320) -> dict[str, pd.DataFrame]:
        out = {}
        for s in symbols:
            df = self._history.get(s)
            if df is None or df.empty:
                out[s] = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                continue
            if self._as_of is not None:
                pos = df.index.searchsorted(self._as_of, side="right")
                df = df.iloc[max(0, pos - limit):pos]
            else:
                df = df.tail(limit)
            out[s] = df
        return out

    def is_market_open(self) -> bool:
        return self.market_open

    def submit_order(self, symbol, side, *, qty=None, notional=None) -> OrderResult:
        price = self._prices.get(symbol)
        if not price or price <= 0:
            return OrderResult(symbol, side, 0.0, 0.0, ok=False, note="no price")
        if notional is not None and qty is None:
            qty = notional / price
        if qty is None or qty <= 0:
            return OrderResult(symbol, side, 0.0, 0.0, ok=False, note="no qty")

        if side == "buy":
            fill = price * (1 + self.slippage)
            cost = qty * fill * (1 + self.commission)
            if cost > self.cash + 1e-6:                 # cap to available cash
                qty = max(0.0, self.cash / (fill * (1 + self.commission)))
                cost = qty * fill * (1 + self.commission)
            if qty <= 0:
                return OrderResult(symbol, side, 0.0, 0.0, ok=False, note="insufficient cash")
            prev_q = self._qty.get(symbol, 0.0)
            prev_avg = self._avg.get(symbol, 0.0)
            new_q = prev_q + qty
            self._avg[symbol] = (prev_q * prev_avg + qty * fill) / new_q if new_q else fill
            self._qty[symbol] = new_q
            self.cash -= cost
            return OrderResult(symbol, side, qty, fill, ok=True, note="filled")

        # sell
        held = self._qty.get(symbol, 0.0)
        qty = min(qty, held)                            # no shorting
        if qty <= 0:
            return OrderResult(symbol, side, 0.0, 0.0, ok=False, note="nothing to sell")
        fill = price * (1 - self.slippage)
        proceeds = qty * fill * (1 - self.commission)
        self._qty[symbol] = held - qty
        self.cash += proceeds
        if abs(self._qty[symbol]) < 1e-9:
            self._qty.pop(symbol, None)
            self._avg.pop(symbol, None)
        return OrderResult(symbol, side, qty, fill, ok=True, note="filled")

    def close_position(self, symbol) -> OrderResult:
        held = self._qty.get(symbol, 0.0)
        if held <= 0:
            return OrderResult(symbol, "sell", 0.0, 0.0, ok=True, note="flat")
        return self.submit_order(symbol, "sell", qty=held)
