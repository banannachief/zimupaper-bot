from datetime import datetime, timezone

from src.config import Config
from src.state import State
from src.telegram_bot import build_status, handle_command


def _state():
    st = State()
    st.record_equity(datetime(2024, 1, 1, tzinfo=timezone.utc), 100_000)
    st.record_equity(datetime(2024, 1, 2, tzinfo=timezone.utc), 100_800)
    return st


def test_status_reports_equity():
    out = build_status(_state(), Config.load())
    assert "Equity" in out and "100,800" in out


def test_pause_resume_requires_authorization():
    st = _state()
    cfg = Config.load()
    # unauthorized cannot pause
    msg = handle_command("/pause", st, cfg, authorized=False)
    assert "Not authorized" in msg and st.manual_pause is False
    # authorized can pause and resume
    handle_command("/pause", st, cfg, authorized=True)
    assert st.manual_pause is True
    handle_command("/resume", st, cfg, authorized=True)
    assert st.manual_pause is False


def test_help_and_unknown():
    st = _state()
    cfg = Config.load()
    assert "/status" in handle_command("/help", st, cfg, authorized=True)
    assert "/status" in handle_command("/wat", st, cfg, authorized=True)


def test_pause_blocks_trading_via_gate():
    from src.broker.base import Account
    from src.risk.manager import RiskManager
    st = _state()
    st.manual_pause = True
    rm = RiskManager(Config.load())
    acct = Account(equity=100_800, cash=0, buying_power=0, last_equity=100_800)
    d = rm.gate(st, acct, datetime(2024, 1, 2, tzinfo=timezone.utc))
    assert d.action == "hold" and "paused" in d.reason.lower()
