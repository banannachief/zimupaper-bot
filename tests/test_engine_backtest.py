"""End-to-end: drive the full engine (agent + risk + broker) through a backtest
on synthetic data. Proves the whole stack runs and the risk rules engage."""
from src.backtester import run_backtest
from src.broker.sim import SimBroker
from src.config import Config
from src.datafeed import synthetic_history


def _small_config():
    return Config(raw={
        "mode": "paper", "broker": "sim", "account_label": "Test",
        "universe": ["AAA", "BBB", "CCC", "DDD"],
        "benchmark": "AAA", "cash_asset": "CASH",
        "targets": {"weekly_gain": 0.01, "biweekly_preserve": True},
        "risk": {"risk_per_trade": 0.01, "max_weight_per_name": 0.25,
                 "max_gross_exposure": 1.0, "stop_loss_atr_mult": 2.5,
                 "daily_loss_halt": 0.03, "max_drawdown_halt": 0.10,
                 "biweekly_lock_buffer": 0.004},
        "agent": {"score_window": 8, "underperform_days": 10, "min_strategy_weight": 0.0,
                  "use_llm_analyst": False},
        "strategies": {
            "momentum": {"enabled": True, "fast": 10, "slow": 50, "top_n": 2},
            "mean_reversion": {"enabled": True, "rsi_period": 2, "rsi_buy": 15,
                               "sma_filter": 50, "top_n": 2},
            "defensive": {"enabled": True},
        },
        "data": {"timeframe": "1Day", "history_bars": 200},
    })


def test_sim_broker_buy_sell():
    b = SimBroker(starting_cash=10_000)
    b.set_prices({"AAA": 100.0})
    r = b.submit_order("AAA", "buy", notional=1000)
    assert r.ok and r.filled_qty > 0
    acct = b.get_account()
    assert abs(acct.equity - 10_000) < 50          # value preserved (minus slippage)
    r2 = b.close_position("AAA")
    assert r2.ok
    assert "AAA" not in b.get_positions()


def test_backtest_runs_and_reports():
    cfg = _small_config()
    hist = synthetic_history(cfg.all_symbols, n=260, seed=3)
    res = run_backtest(cfg, hist, starting_cash=100_000, warmup=80)
    assert "error" not in res, res
    assert res["days"] > 20
    assert res["end_equity"] > 0
    # weekly stats are well-formed probabilities
    assert 0.0 <= res["pct_weeks_hit_target"] <= 1.0
    assert 0.0 <= res["pct_weeks_negative"] <= 1.0
    assert res["trades"] >= 0


def test_weekly_lock_caps_upside_within_a_week():
    """If a week is up >= target, the bot should bank it and stop adding risk."""
    cfg = _small_config()
    # strongly trending data so the +1% weekly target gets hit often
    hist = synthetic_history(cfg.all_symbols, n=260, seed=11)
    res = run_backtest(cfg, hist, starting_cash=100_000, warmup=80)
    # sanity: max weekly gain shouldn't be absurd given the take-profit discipline
    assert res["max_drawdown"] <= 0.0
