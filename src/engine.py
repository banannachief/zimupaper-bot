"""The trading engine — orchestrates one full decision/trade cycle.

This is what the GitHub Actions cron invokes (via run.py) and what the
backtester drives day by day. It is broker-agnostic: the same code runs against
Alpaca (paper/live) and the offline SimBroker.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .agent.controller import Controller
from .broker.base import Broker
from .risk.manager import RiskManager
from .strategies import build_strategies


def _data_too_thin(data: dict[str, pd.DataFrame], config, bench_df) -> bool:
    """True if the feed looks broken — guard against liquidating on an outage."""
    if bench_df is None or len(bench_df) < 50:
        return True
    usable = sum(1 for s in config.universe
                 if data.get(s) is not None and len(data.get(s)) >= 50)
    return usable < max(2, len(config.universe) // 2)


def _latest_prices(data: dict[str, pd.DataFrame]) -> dict[str, float]:
    out = {}
    for sym, df in data.items():
        if df is not None and not df.empty:
            out[sym] = float(df["close"].iloc[-1])
    return out


def _execute(broker: Broker, order, state, now, logs: list):
    if order.side == "buy":
        res = broker.submit_order(order.symbol, "buy", notional=order.notional)
    else:
        if order.reason == "exit":
            res = broker.close_position(order.symbol)
        else:
            res = broker.submit_order(order.symbol, "sell", qty=order.qty)
    if res.ok:
        qty = res.filled_qty or (order.qty or 0.0)
        state.log_trade(now, order.symbol, order.side, qty, res.avg_price or 0.0,
                        order.reason)
    logs.append(f"{order.side} {order.symbol} "
                f"{order.notional or order.qty} -> {'ok' if res.ok else res.note}")
    return res


def run_cycle(broker: Broker, config, state, now: datetime | None = None, *,
              market_open: bool | None = None, render: bool = True,
              persist: bool = True) -> dict:
    """Run one cycle. Returns a small summary dict for logging/telemetry."""
    now = now or datetime.now(timezone.utc)
    strategies = build_strategies(config)
    controller = Controller(strategies, config)
    risk = RiskManager(config)
    logs: list[str] = []

    account = broker.get_account()
    positions = broker.get_positions()
    data = broker.get_bars(config.all_symbols, config.data.get("timeframe", "1Day"),
                           int(config.data.get("history_bars", 320)))

    bench_df = data.get(config.benchmark)
    bench_close = float(bench_df["close"].iloc[-1]) if (
        bench_df is not None and not bench_df.empty) else None
    state.record_equity(now, account.equity, bench_close)

    is_open = broker.is_market_open() if market_open is None else market_open

    decision = risk.gate(state, account, now)
    summary = {"t": now.isoformat(), "equity": round(account.equity, 2),
               "weekly": round(state.weekly_return(), 4),
               "biweekly": round(state.biweekly_return(), 4),
               "drawdown": round(state.current_drawdown(), 4),
               "action": decision.action, "reason": decision.reason}

    if decision.action == "liquidate":
        broker.close_all()
        state.add_note(f"{now.date()}: LIQUIDATE — {decision.reason}")
        logs.append(f"liquidate: {decision.reason}")
    elif decision.action == "hold" or not is_open:
        summary["action"] = decision.action if decision.action == "hold" else "hold-market-closed"
        summary["reason"] = decision.reason if decision.action == "hold" else "market closed"
        state.add_note(f"{now.date()}: HOLD — "
                       f"{decision.reason if decision.action == 'hold' else 'market closed'}")
    elif _data_too_thin(data, config, bench_df):
        # Safety: a broken/empty data feed must NOT trigger trading. Empty target
        # weights would otherwise liquidate the whole book on a transient outage.
        state.add_note(f"{now.date()}: HOLD — insufficient market data; not trading")
        summary["action"] = "hold-nodata"
        logs.append("insufficient data — holding")
    else:  # trade
        # 1) honour trailing stop-losses first
        breached = risk.update_stops(state, positions, data)
        for sym in breached:
            _execute(broker, _StopOrder(sym), state, now, logs)
        if breached:
            positions = broker.get_positions()

        # 2) agent decides target portfolio — but only re-decide on a cadence
        #    (e.g. weekly). Between decisions we reuse the last allocation; the
        #    risk layer + rebalance band still run daily. Cuts churn and compute.
        cadence = int(config.agent.get("decision_cadence_days", 5))
        reuse = False
        if (state.last_decision_date and state.last_target_weights
                and not state.restrategize_needed):
            try:
                last = datetime.fromisoformat(state.last_decision_date)
                reuse = (now - last).days < cadence
            except Exception:
                reuse = False

        if reuse:
            target_weights = dict(state.last_target_weights)
            regime_label = state.last_regime or "n/a"
            strat_weights = state.last_strategy_weights or {}
        else:
            # optional DeepSeek sentiment (only on a real decision, not every cycle)
            sentiment = {}
            if config.agent.get("use_sentiment", False):
                try:
                    from .agent.sentiment import analyze
                    news = broker.get_news(config.universe)
                    sentiment = analyze(news, config.universe)
                except Exception as e:
                    logs.append(f"sentiment skipped: {type(e).__name__}")
            dec = controller.decide(data, state, sentiment=sentiment)
            target_weights = dec.target_weights
            regime_label = dec.regime.label
            strat_weights = dec.strategy_weights
            state.last_decision_date = now.isoformat()
            state.last_target_weights = target_weights
            state.last_regime = regime_label
            state.last_strategy_weights = strat_weights
            state.log_decision(now, regime_label, strat_weights, target_weights,
                               note=f"{dec.note}; risk_scale={decision.risk_scale:.2f}")

        target_dollars = risk.size_targets(target_weights, account, data,
                                            decision.risk_scale)
        prices = _latest_prices(data)
        orders = risk.make_orders(target_dollars, positions, prices, account.equity)
        for o in orders:
            _execute(broker, o, state, now, logs)

        summary["regime"] = regime_label
        summary["strategies"] = {k: round(v, 3) for k, v in strat_weights.items()}

    # refresh snapshot for the dashboard
    pos = broker.get_positions()
    state.last_positions = [
        {"symbol": p.symbol, "qty": round(p.qty, 4),
         "price": round(p.current_price, 2),
         "value": round(p.market_value, 2),
         "stop": round(state.stops.get(p.symbol, 0.0), 2)}
        for p in pos.values()
    ]
    summary["positions"] = len(pos)
    summary["logs"] = logs

    if render:
        from .dashboard.render import render_dashboard
        render_dashboard(state, config)

    if persist:
        state.save()
    return summary


class _StopOrder:
    """Internal marker so _execute closes a stopped-out position."""
    def __init__(self, symbol):
        self.symbol = symbol
        self.side = "sell"
        self.reason = "exit"
        self.qty = None
        self.notional = None
