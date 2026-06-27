"""Persistent bot state (JSON on disk, committed back to the repo each run).

This is the single source of truth for: the equity curve, the current week's
take-profit progress, the rolling two-week preservation block, halt flags,
open stop levels, the trade log, and the agent's decision log.

Everything is plain JSON-serialisable so it round-trips cleanly and powers the
dashboard without a database.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import calendar_utils as cal

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = ROOT / "state" / "state.json"


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat()


@dataclass
class WeekBlock:
    """A trading week's profit-target accounting."""

    key: str = ""              # Monday ISO date
    start_equity: float = 0.0
    peak_equity: float = 0.0
    locked: bool = False       # True once +weekly_gain hit -> stop trading this week


@dataclass
class BiWeekBlock:
    """A two-week capital-preservation block."""

    key: int = -1
    start_equity: float = 0.0
    peak_equity: float = 0.0
    defending: bool = False    # True once we're locking in a non-negative close


@dataclass
class State:
    created_at: str = ""
    updated_at: str = ""
    starting_equity: float = 0.0
    peak_equity: float = 0.0
    last_equity: float = 0.0

    week: WeekBlock = field(default_factory=WeekBlock)
    biweek: BiWeekBlock = field(default_factory=BiWeekBlock)

    # halt machinery
    daily_halt_date: str = ""        # date string; no new trades that day
    drawdown_halted: bool = False    # global: flat + needs re-strategize
    restrategize_needed: bool = False
    manual_pause: bool = False       # user paused trading via Telegram (/pause)

    # telegram interaction
    tg_offset: int = 0               # last processed Telegram update_id

    # per-symbol protective stop prices
    stops: dict[str, float] = field(default_factory=dict)

    # rolling logs (capped to keep the file small)
    equity_curve: list[dict] = field(default_factory=list)   # {t, equity}
    benchmark_curve: list[dict] = field(default_factory=list)  # {t, value}
    trades: list[dict] = field(default_factory=list)          # {t, symbol, side, qty, price, reason}
    decisions: list[dict] = field(default_factory=list)       # {t, regime, strategies, weights, note}

    # last computed snapshot for the dashboard
    last_positions: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    MAX_LOG: int = 5000

    # ------------------------------------------------------------------ I/O
    @classmethod
    def load(cls, path: str | Path | None = None) -> "State":
        p = Path(path) if path else DEFAULT_STATE_PATH
        if not p.exists():
            return cls()
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        st = cls()
        for k, v in data.items():
            if k == "week":
                st.week = WeekBlock(**v)
            elif k == "biweek":
                st.biweek = BiWeekBlock(**v)
            elif hasattr(st, k):
                setattr(st, k, v)
        return st

    def save(self, path: str | Path | None = None) -> None:
        p = Path(path) if path else DEFAULT_STATE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, default=str)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("MAX_LOG", None)
        return d

    # ------------------------------------------------- equity / period mgmt
    def record_equity(self, ts: datetime, equity: float, benchmark: float | None = None) -> None:
        """Update equity, roll week/two-week blocks, refresh peaks. Call once per cycle."""
        if not self.created_at:
            self.created_at = _iso(ts)
            self.starting_equity = equity
            self.peak_equity = equity

        self.updated_at = _iso(ts)
        self.last_equity = equity
        self.peak_equity = max(self.peak_equity, equity)

        # --- weekly roll ---
        wk = cal.week_key(ts)
        if self.week.key != wk:
            self.week = WeekBlock(key=wk, start_equity=equity, peak_equity=equity, locked=False)
        else:
            self.week.peak_equity = max(self.week.peak_equity, equity)

        # --- two-week roll ---
        bk = cal.block_key(ts)
        if self.biweek.key != bk:
            self.biweek = BiWeekBlock(key=bk, start_equity=equity, peak_equity=equity, defending=False)
        else:
            self.biweek.peak_equity = max(self.biweek.peak_equity, equity)

        self.equity_curve.append({"t": _iso(ts), "equity": round(equity, 2)})
        if benchmark is not None:
            self.benchmark_curve.append({"t": _iso(ts), "value": round(benchmark, 4)})
        self._cap(self.equity_curve)
        self._cap(self.benchmark_curve)

    # ------------------------------------------------------------ accessors
    def weekly_return(self) -> float:
        if self.week.start_equity <= 0:
            return 0.0
        return self.last_equity / self.week.start_equity - 1.0

    def biweekly_return(self) -> float:
        if self.biweek.start_equity <= 0:
            return 0.0
        return self.last_equity / self.biweek.start_equity - 1.0

    def total_return(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return self.last_equity / self.starting_equity - 1.0

    def current_drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return self.last_equity / self.peak_equity - 1.0

    # ------------------------------------------------------------- logging
    def log_trade(self, ts: datetime, symbol: str, side: str, qty: float,
                  price: float, reason: str = "") -> None:
        self.trades.append({
            "t": _iso(ts), "symbol": symbol, "side": side,
            "qty": round(qty, 6), "price": round(price, 4), "reason": reason,
        })
        self._cap(self.trades)

    def log_decision(self, ts: datetime, regime: str, strategy_weights: dict,
                     target_weights: dict, note: str = "") -> None:
        self.decisions.append({
            "t": _iso(ts),
            "regime": regime,
            "strategies": {k: round(v, 4) for k, v in strategy_weights.items()},
            "weights": {k: round(v, 4) for k, v in target_weights.items() if abs(v) > 1e-9},
            "note": note,
        })
        self._cap(self.decisions)

    def add_note(self, msg: str) -> None:
        self.notes.append(msg)
        self.notes = self.notes[-50:]

    def _cap(self, lst: list) -> None:
        if len(lst) > self.MAX_LOG:
            del lst[: len(lst) - self.MAX_LOG]
