from src.config import Config
from src.evaluation import clone_config, grid_combos, objective


def test_clone_config_applies_dotted_overrides():
    base = Config.load()
    c = clone_config(base, {"strategies.momentum.slow": 999,
                            "targets.weekly_gain": 0.05})
    assert c.strategies["momentum"]["slow"] == 999
    assert c.weekly_gain == 0.05
    # original is untouched (deep copy)
    assert base.strategies["momentum"]["slow"] != 999


def test_grid_combos_cartesian():
    g = {"a": [1, 2], "b": [10, 20, 30]}
    combos = grid_combos(g)
    assert len(combos) == 6
    assert {"a": 1, "b": 10} in combos
    assert grid_combos({}) == [{}]


def test_objective_prefers_higher_sharpe_fewer_2wk_losses():
    good = {"sharpe": 1.2, "max_drawdown": -0.08, "pct_2wk_blocks_negative": 0.2}
    bad = {"sharpe": 0.3, "max_drawdown": -0.25, "pct_2wk_blocks_negative": 0.5}
    assert objective(good) > objective(bad)
    assert objective({"error": "x"}) < -10
    # catastrophic drawdown is penalized
    blowup = {"sharpe": 2.0, "max_drawdown": -0.5, "pct_2wk_blocks_negative": 0.1}
    safe = {"sharpe": 1.0, "max_drawdown": -0.1, "pct_2wk_blocks_negative": 0.1}
    assert objective(safe) > objective(blowup) - 5  # penalty pulls blowup down
