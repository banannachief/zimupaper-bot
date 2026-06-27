from datetime import datetime, timedelta, timezone

from src import calendar_utils as cal
from src.state import State


def _dt(y, m, d):
    return datetime(y, m, d, 16, 0, tzinfo=timezone.utc)


def test_week_and_block_boundaries():
    mon = _dt(2024, 1, 1)        # a Monday
    wed = _dt(2024, 1, 3)
    next_mon = _dt(2024, 1, 8)
    assert cal.week_key(mon) == cal.week_key(wed)
    assert cal.week_key(mon) != cal.week_key(next_mon)
    # two weeks later -> next block
    assert cal.block_number(_dt(2024, 1, 15)) == cal.block_number(mon) + 1


def test_weekly_rollover_and_returns():
    st = State()
    st.record_equity(_dt(2024, 1, 1), 100_000)
    st.record_equity(_dt(2024, 1, 3), 101_000)
    assert abs(st.weekly_return() - 0.01) < 1e-9
    # new week resets the weekly base
    st.record_equity(_dt(2024, 1, 8), 101_000)
    assert abs(st.weekly_return()) < 1e-9
    assert abs(st.total_return() - 0.01) < 1e-9


def test_biweekly_window():
    st = State()
    d0 = _dt(2024, 1, 1)                            # a Monday
    st.record_equity(d0, 100_000)
    st.record_equity(d0 + timedelta(days=1), 102_000)   # same week -> same block
    assert abs(st.biweekly_return() - 0.02) < 1e-9
    st.record_equity(d0 + timedelta(days=14), 102_000)  # +2 weeks -> next block resets
    assert abs(st.biweekly_return()) < 1e-9


def test_drawdown_tracking():
    st = State()
    st.record_equity(_dt(2024, 1, 1), 100_000)
    st.record_equity(_dt(2024, 1, 2), 110_000)    # new peak
    st.record_equity(_dt(2024, 1, 3), 99_000)
    assert abs(st.current_drawdown() - (99_000 / 110_000 - 1)) < 1e-9


def test_state_roundtrip(tmp_path):
    st = State()
    st.record_equity(_dt(2024, 1, 1), 100_000)
    st.log_trade(_dt(2024, 1, 1), "SPY", "buy", 10, 400.0, "test")
    p = tmp_path / "state.json"
    st.save(p)
    loaded = State.load(p)
    assert loaded.last_equity == 100_000
    assert loaded.trades[-1]["symbol"] == "SPY"
    assert loaded.week.key == st.week.key
