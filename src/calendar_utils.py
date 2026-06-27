"""Calendar helpers for week / two-week-block accounting.

Anchored to a fixed Monday epoch so week and block boundaries are continuous
and calendar-accurate (no ISO year-boundary parity glitches).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

EPOCH_MONDAY = date(1970, 1, 5)  # a Monday


def _as_date(d: date | datetime) -> date:
    return d.date() if isinstance(d, datetime) else d


def week_start(d: date | datetime) -> date:
    """Monday of the week containing ``d``."""
    dd = _as_date(d)
    return dd - timedelta(days=dd.weekday())


def week_number(d: date | datetime) -> int:
    """Continuous week index since the Monday epoch."""
    return (week_start(d) - EPOCH_MONDAY).days // 7


def block_number(d: date | datetime) -> int:
    """Continuous two-week-block index since the epoch."""
    return week_number(d) // 2


def week_key(d: date | datetime) -> str:
    return week_start(d).isoformat()


def block_key(d: date | datetime) -> int:
    return block_number(d)
