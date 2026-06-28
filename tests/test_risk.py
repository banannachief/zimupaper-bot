from datetime import datetime, timezone

from src.broker.base import Account, Position
from src.config import Config
from src.datafeed import synthetic_history
from src.risk.manager import RiskManager
from src.state import State


def _dt(d=1):
    return datetime(2024, 1, d, 16, 0, tzinfo=timezone.utc)


def cfg():
    return Config.load()


def test_weekly_take_profit_liquidates():
    c = cfg()
    rm = RiskManager(c)
    st = State()
    st.record_equity(_dt(1), 100_000)
    st.record_equity(_dt(2), 101_500)         # +1.5% week, target is +1%
    acct = Account(equity=101_500, cash=0, buying_power=0, last_equity=101_000)
    d = rm.gate(st, acct, _dt(2))
    assert d.action == "liquidate"
    assert st.week.locked is True
    # next call same week -> hold (resting)
    assert rm.gate(st, acct, _dt(2)).action == "hold"


def test_daily_loss_halt():
    c = cfg()
    rm = RiskManager(c)
    st = State()
    st.record_equity(_dt(1), 100_000)
    st.record_equity(_dt(1), 96_000)
    acct = Account(equity=96_000, cash=96_000, buying_power=96_000, last_equity=100_000)
    d = rm.gate(st, acct, _dt(1))
    assert d.action == "liquidate"
    assert st.daily_halt_date == _dt(1).date().isoformat()
    assert rm.gate(st, acct, _dt(1)).action == "hold"      # halted rest of day


def test_drawdown_halt_and_recovery():
    c = cfg()
    rm = RiskManager(c)
    st = State()
    st.record_equity(_dt(1), 100_000)
    st.record_equity(_dt(2), 110_000)          # peak
    st.record_equity(_dt(2), 98_000)           # -10.9% drawdown
    acct = Account(equity=98_000, cash=0, buying_power=0, last_equity=99_000)
    d = rm.gate(st, acct, _dt(2))
    assert d.action == "liquidate"
    assert st.drawdown_halted is True
    # recovery above half the halt threshold re-enables trading.
    # Use the NEXT week (day 8) so the weekly take-profit doesn't fire first.
    st.record_equity(_dt(8), 109_000)
    acct2 = Account(equity=109_000, cash=0, buying_power=0, last_equity=109_000)
    d2 = rm.gate(st, acct2, _dt(8))
    assert st.drawdown_halted is False
    assert d2.action in ("trade", "hold")


def test_capital_base_caps_deployment():
    """With capital_base set, sizing uses the smaller base, not full equity."""
    c = Config.load()
    c.raw["risk"]["capital_base"] = 20000
    rm = RiskManager(c)
    hist = synthetic_history(["AAA", "BBB", "BIL"], n=60, seed=2)
    # account has 100k but only 20k should be deployable
    acct = Account(equity=100_000, cash=100_000, buying_power=100_000, last_equity=100_000)
    targets = rm.size_targets({"AAA": 0.5, "BBB": 0.5}, acct, hist, risk_scale=1.0)
    assert sum(targets.values()) <= 20_000 + 1     # never deploy more than the base


def test_vol_cap_limits_position():
    c = cfg()
    rm = RiskManager(c)
    hist = synthetic_history(["AAA", "BIL"], n=60, seed=1)
    acct = Account(equity=100_000, cash=100_000, buying_power=100_000, last_equity=100_000)
    targets = rm.size_targets({"AAA": 1.0, "BIL": 0.0}, acct, hist, risk_scale=1.0)
    # a single risk name can never exceed the per-name cap of equity
    assert targets.get("AAA", 0) <= c.risk["max_weight_per_name"] * acct.equity + 1


def test_make_orders_buy_and_exit():
    c = cfg()
    rm = RiskManager(c)
    # fresh buy
    orders = rm.make_orders({"SPY": 5000.0}, {}, {"SPY": 100.0}, 100_000)
    assert any(o.symbol == "SPY" and o.side == "buy" and o.notional == 5000 for o in orders)
    # exit when target is ~0 but we hold
    pos = {"SPY": Position("SPY", qty=50, avg_entry_price=100, current_price=100)}
    orders2 = rm.make_orders({}, pos, {"SPY": 100.0}, 100_000)
    assert any(o.symbol == "SPY" and o.side == "sell" and o.reason == "exit" for o in orders2)
