"""The meta-controller: combines regime, strategy scoring, live-performance
feedback and (optional) an LLM analyst into one set of target weights.

Decision flow each cycle:
  1. Detect market regime from the benchmark -> a risk budget.
  2. Shadow-score every enabled strategy on the recent window.
  3. Feed in LIVE feedback: if the book itself has been losing recently, or a
     re-strategize flag is set after a drawdown halt, cut the risk budget.
  4. Allocate capital across strategies (winners get more; if none work, defend).
  5. Blend each strategy's desired holdings into final target weights.
  6. (Optional) let a Claude analyst nudge — but the risk layer always vetoes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import selector
from .regime import Regime, detect_regime


@dataclass
class Decision:
    regime: Regime
    scores: dict[str, float] = field(default_factory=dict)
    strategy_weights: dict[str, float] = field(default_factory=dict)
    target_weights: dict[str, float] = field(default_factory=dict)
    note: str = ""


class Controller:
    def __init__(self, strategies: dict, config):
        self.strategies = strategies
        self.config = config
        self.agent_cfg = config.agent

    def decide(self, history: dict[str, pd.DataFrame], state) -> Decision:
        cfg = self.config
        context = {"cash_asset": cfg.cash_asset, "benchmark": cfg.benchmark}
        universe = cfg.universe
        enabled = list(self.strategies.keys())

        bench = history.get(cfg.benchmark)
        bench_close = bench["close"] if (bench is not None and not bench.empty) else None
        regime = detect_regime(bench_close)

        # --- score each strategy on recent shadow performance ---
        window = int(self.agent_cfg.get("score_window", 20))
        scores: dict[str, float] = {}
        for name, strat in self.strategies.items():
            rets = selector.shadow_returns(strat, history, universe, cfg.cash_asset,
                                           context, window=window)
            scores[name] = selector.score_returns(rets)

        # --- live-performance feedback (truly agentic: react to OWN results) ---
        risk_budget = regime.risk_budget
        notes = [f"regime={regime.label}({regime.note})"]

        # Only de-risk on a REAL drawdown over the window, not on normal noise —
        # a hair-trigger here keeps the book out of healthy uptrends.
        underperf_days = int(self.agent_cfg.get("underperform_days", 15))
        underperf_dd = float(self.agent_cfg.get("underperform_drawdown", 0.03))
        live_ret = _recent_equity_return(state, underperf_days)
        if live_ret is not None and live_ret < -underperf_dd:
            risk_budget *= 0.7
            notes.append(f"book down {live_ret:+.2%} over ~{underperf_days}d -> de-risk")

        if getattr(state, "restrategize_needed", False):
            risk_budget *= 0.25
            notes.append("post-drawdown re-strategize -> minimal risk")

        risk_budget = max(0.0, min(risk_budget, float(cfg.risk.get("max_gross_exposure", 1.0))))

        # --- allocate across strategies ---
        strat_weights = selector.allocate(
            scores, risk_budget, enabled,
            min_weight=float(self.agent_cfg.get("min_strategy_weight", 0.0)),
        )

        # --- blend into symbol target weights ---
        target: dict[str, float] = {}
        for name, alloc in strat_weights.items():
            if alloc <= 0:
                continue
            sw = self.strategies[name].target_weights(history, universe, context)
            for sym, w in sw.items():
                target[sym] = target.get(sym, 0.0) + alloc * w

        # --- optional LLM analyst (off by default; advisory only) ---
        if self.agent_cfg.get("use_llm_analyst", False):
            try:
                from .llm_analyst import advise
                target, adv_note = advise(target, regime, scores, self.config)
                if adv_note:
                    notes.append(f"analyst:{adv_note}")
            except Exception as e:  # never let the analyst break a cycle
                notes.append(f"analyst-skip:{type(e).__name__}")

        target = {s: round(w, 6) for s, w in target.items() if w > 1e-6}
        return Decision(regime=regime, scores=scores, strategy_weights=strat_weights,
                        target_weights=target, note="; ".join(notes))


def _recent_equity_return(state, days: int) -> float | None:
    curve = getattr(state, "equity_curve", []) or []
    if len(curve) < 2:
        return None
    window = curve[-(days + 1):]
    first = window[0].get("equity")
    last = window[-1].get("equity")
    if not first or first <= 0:
        return None
    return last / first - 1.0
