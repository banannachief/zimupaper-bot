import numpy as np
import pandas as pd

from src.agent import selector
from src.agent.regime import detect_regime
from src.datafeed import synthetic_history
from src.strategies import build_strategies
from src.strategies.defensive import DefensiveStrategy
from src.strategies.momentum import MomentumStrategy


CONTEXT = {"cash_asset": "BIL", "benchmark": "SPY"}
UNIVERSE = ["SPY", "QQQ", "XLK", "XLF"]


def _hist(n=320, seed=7):
    return synthetic_history(UNIVERSE + ["BIL"], n=n, seed=seed)


def _valid_weights(w):
    assert all(v >= 0 for v in w.values())
    assert sum(w.values()) <= 1.0 + 1e-6


def test_momentum_weights_valid():
    s = MomentumStrategy({"fast": 20, "slow": 100, "top_n": 4})
    w = s.target_weights(_hist(), UNIVERSE, CONTEXT)
    _valid_weights(w)


def test_defensive_holds_cash():
    s = DefensiveStrategy({})
    w = s.target_weights(_hist(), UNIVERSE, CONTEXT)
    assert w == {"BIL": 1.0}


def test_build_strategies_from_config():
    from src.config import Config
    strats = build_strategies(Config.load())
    assert "momentum" in strats and "defensive" in strats


def test_regime_detection_shapes():
    # strong uptrend benchmark
    up = pd.Series(100 * np.cumprod(1 + np.full(260, 0.001)))
    r = detect_regime(up)
    assert r.label in ("bull", "chop", "high_vol", "bear")
    assert 0 <= r.risk_budget <= 1
    # insufficient history -> neutral
    short = pd.Series(np.linspace(100, 110, 50))
    assert detect_regime(short).label == "chop"


def test_selector_allocate_defends_when_nothing_works():
    enabled = ["momentum", "mean_reversion", "defensive"]
    # all risk strategies scoring negative -> everything to defensive
    w = selector.allocate({"momentum": -1, "mean_reversion": -0.5, "defensive": 0},
                          risk_budget=1.0, enabled=enabled)
    assert w == {"defensive": 1.0}
    # a winner gets the risk budget, defensive takes the remainder
    w2 = selector.allocate({"momentum": 2.0, "mean_reversion": 0.0, "defensive": 0},
                           risk_budget=0.6, enabled=enabled)
    assert abs(w2.get("momentum", 0) - 0.6) < 1e-9
    assert abs(w2.get("defensive", 0) - 0.4) < 1e-9


def test_shadow_returns_runs():
    s = MomentumStrategy({"fast": 10, "slow": 50, "top_n": 3})
    r = selector.shadow_returns(s, _hist(n=200), UNIVERSE, "BIL", CONTEXT, window=10)
    assert isinstance(r, pd.Series)
    score = selector.score_returns(r)
    assert isinstance(score, float)
