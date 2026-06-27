"""Broker interface and shared data types.

All trading logic talks to this interface only, so swapping Alpaca <-> the
offline simulator (or a future broker) changes nothing upstream.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class Account:
    equity: float          # total account value (cash + positions)
    cash: float
    buying_power: float
    last_equity: float = 0.0   # equity at previous close (for intraday daily PnL)


@dataclass
class Position:
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.qty * self.current_price


@dataclass
class OrderResult:
    symbol: str
    side: str
    filled_qty: float
    avg_price: float
    ok: bool = True
    note: str = ""


class Broker(ABC):
    """Minimal trading surface the engine relies on."""

    @abstractmethod
    def get_account(self) -> Account: ...

    @abstractmethod
    def get_positions(self) -> dict[str, Position]: ...

    @abstractmethod
    def get_bars(self, symbols: list[str], timeframe: str = "1Day",
                 limit: int = 320) -> dict[str, pd.DataFrame]:
        """Return {symbol: DataFrame[open,high,low,close,volume]} indexed by date."""

    @abstractmethod
    def is_market_open(self) -> bool: ...

    @abstractmethod
    def submit_order(self, symbol: str, side: str, *, qty: float | None = None,
                     notional: float | None = None) -> OrderResult: ...

    @abstractmethod
    def close_position(self, symbol: str) -> OrderResult: ...

    def close_all(self) -> list[OrderResult]:
        results = []
        for sym in list(self.get_positions().keys()):
            results.append(self.close_position(sym))
        return results
