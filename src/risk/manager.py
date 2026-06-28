"""Risk manager.

Turns the agent's *desired* portfolio into *concrete, safe* orders, and gates
trading entirely when protection rules fire. The hard rules, in priority order:

  1. Weekly take-profit  — once the week is up >= weekly_gain (default +1%),
     liquidate to cash and stop trading until next week.
  2. Daily loss halt     — down >= daily_loss_halt intraday -> flatten, stop
     for the rest of the day.
  3. Drawdown halt       — drawdown from peak >= max_drawdown_halt -> go to
     cash and flag a re-strategize; auto-clears once recovered.
  4. Two-week preservation — defend a non-negative close on every 2-week block
     by scaling risk down as the block nears breakeven after being up.

Then, when trading is allowed:
  * volatility-targeted sizing so each position risks ~risk_per_trade of equity
    to its stop,
  * per-name weight cap and no leverage,
  * trailing ATR stop-losses, checked every cycle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from ..indicators import atr


@dataclass
class Order:
    symbol: str
    side: str                 # buy | sell
    notional: float | None = None
    qty: float | None = None
    reason: str = ""


@dataclass
class RiskDecision:
    action: str               # trade | liquidate | hold
    reason: str
    risk_scale: float = 1.0   # extra clamp applied to risk-asset weights
    extras: dict = field(default_factory=dict)


class RiskManager:
    def __init__(self, config):
        self.c = config
        r = config.risk
        self.risk_per_trade = float(r.get("risk_per_trade", 0.01))
        self.max_weight = float(r.get("max_weight_per_name", 0.20))
        self.max_gross = float(r.get("max_gross_exposure", 1.0))
        self.stop_mult = float(r.get("stop_loss_atr_mult", 2.5))
        self.rebalance_band = float(r.get("rebalance_band", 0.02))
        self.daily_halt = float(r.get("daily_loss_halt", 0.03))
        self.max_dd_halt = float(r.get("max_drawdown_halt", 0.10))
        self.biweekly_buffer = float(r.get("biweekly_lock_buffer", 0.004))
        self.capital_base = float(r.get("capital_base", 0.0))   # 0 = use full account
        self.weekly_gain = config.weekly_gain
        self.cash_asset = config.cash_asset

    # ------------------------------------------------------------- gating
    def gate(self, state, account, now: datetime) -> RiskDecision:
        """Decide whether/how to trade. May mutate halt flags on ``state``."""
        equity = account.equity

        # User override: paused via Telegram /pause -> no new trades.
        if getattr(state, "manual_pause", False):
            return RiskDecision("hold", "paused by user (Telegram /pause)")

        # Weekly take-profit: lock in once the +1% week target is hit.
        if state.week.locked:
            return RiskDecision("hold", f"weekly +{self.weekly_gain:.1%} target already "
                                        f"hit — resting until next week")
        if state.weekly_return() >= self.weekly_gain:
            state.week.locked = True
            return RiskDecision("liquidate", f"weekly target hit "
                                             f"({state.weekly_return():+.2%}) — banking it")

        # Daily loss halt — if already halted today, hold before re-checking the trigger.
        if state.daily_halt_date == now.date().isoformat():
            return RiskDecision("hold", "daily loss halt active — no trading today")
        if account.last_equity > 0:
            daily = equity / account.last_equity - 1.0
            if daily <= -self.daily_halt:
                state.daily_halt_date = now.date().isoformat()
                return RiskDecision("liquidate", f"daily loss {daily:+.2%} <= "
                                                 f"-{self.daily_halt:.1%} — halting today")

        # Max drawdown halt (and auto-recovery).
        dd = state.current_drawdown()
        if dd <= -self.max_dd_halt and not state.drawdown_halted:
            state.drawdown_halted = True
            state.restrategize_needed = True
            return RiskDecision("liquidate", f"drawdown {dd:+.2%} <= -{self.max_dd_halt:.1%} "
                                             f"— to cash & re-strategizing")
        if state.drawdown_halted:
            if dd > -self.max_dd_halt * 0.5:
                state.drawdown_halted = False
                state.restrategize_needed = False
                state.add_note(f"drawdown recovered to {dd:+.2%} — trading re-enabled")
            else:
                return RiskDecision("hold", f"drawdown halt active ({dd:+.2%})")

        # Two-week preservation: defend a non-negative close.
        scale, why = self._biweekly_scale(state)
        return RiskDecision("trade", why or "ok", risk_scale=scale)

    def _biweekly_scale(self, state) -> tuple[float, str]:
        if not self.c.targets.get("biweekly_preserve", True):
            return 1.0, ""
        bw = state.biweek
        if bw.start_equity <= 0:
            return 1.0, ""
        ret = state.biweekly_return()
        peak_ret = bw.peak_equity / bw.start_equity - 1.0
        # Once we've been up beyond the buffer, switch into "defend" mode.
        if peak_ret >= self.biweekly_buffer:
            bw.defending = True
        if bw.defending:
            # Closer to breakeven -> de-risk harder to lock the non-negative close.
            if ret <= self.biweekly_buffer * 0.5:
                return 0.25, f"defending 2-wk gain (now {ret:+.2%}) — heavy de-risk"
            if ret <= self.biweekly_buffer:
                return 0.5, f"defending 2-wk gain (now {ret:+.2%}) — de-risk"
        if ret < 0:
            return 0.5, f"2-wk block underwater ({ret:+.2%}) — cautious"
        return 1.0, ""

    # ---------------------------------------------------- sizing & orders
    def size_targets(self, target_weights: dict[str, float], account,
                     data: dict[str, pd.DataFrame], risk_scale: float) -> dict[str, float]:
        """Convert target weights -> target dollar values with all caps applied.

        If a capital_base is set (e.g. $20k), the bot only ever deploys that much
        of your account — the rest is left untouched. All sizing is measured
        against the smaller of capital_base and actual equity.
        """
        equity = account.equity
        if self.capital_base and self.capital_base > 0:
            equity = min(equity, self.capital_base)
        out: dict[str, float] = {}
        for sym, w in target_weights.items():
            if w <= 0:
                continue
            if sym == self.cash_asset:
                out[sym] = w * equity            # cash-like: no vol cap, no scale
                continue
            capped = min(w * risk_scale, self.max_weight)
            vc = self._vol_cap(data, sym)
            capped = min(capped, vc)
            if capped > 1e-4:
                out[sym] = capped * equity
        # enforce gross exposure (excluding cash asset which is "safe")
        risk_total = sum(v for s, v in out.items() if s != self.cash_asset)
        cap_total = self.max_gross * equity
        if risk_total > cap_total and risk_total > 0:
            f = cap_total / risk_total
            for s in out:
                if s != self.cash_asset:
                    out[s] *= f
        return out

    def _vol_cap(self, data: dict[str, pd.DataFrame], sym: str) -> float:
        """Max weight so the position risks <= risk_per_trade of equity to its stop."""
        df = data.get(sym)
        if df is None or len(df) < 20:
            return self.max_weight
        a = atr(df, 14).iloc[-1]
        price = df["close"].iloc[-1]
        if not price or price <= 0 or pd.isna(a) or a <= 0:
            return self.max_weight
        stop_dist_pct = self.stop_mult * (a / price)
        if stop_dist_pct <= 0:
            return self.max_weight
        return self.risk_per_trade / stop_dist_pct

    def make_orders(self, target_dollars: dict[str, float], positions: dict,
                    prices: dict[str, float], equity: float) -> list[Order]:
        """Rebalance current positions toward the dollar targets.

        A no-trade band suppresses tiny daily adjustments (the main source of
        churn): an existing holding is only nudged when it has drifted more than
        ``rebalance_band`` of equity. Fresh entries and full exits always go
        through (subject to the minimum trade size).
        """
        min_trade = max(20.0, 0.005 * equity)
        band = max(min_trade, self.rebalance_band * equity)
        orders: list[Order] = []
        symbols = set(target_dollars) | set(positions)
        for sym in sorted(symbols):
            price = prices.get(sym, 0.0)
            cur_val = positions[sym].market_value if sym in positions else 0.0
            tgt_val = target_dollars.get(sym, 0.0)
            delta = tgt_val - cur_val
            held = sym in positions

            # always honour full exits and brand-new entries
            if held and tgt_val < min_trade:
                orders.append(Order(sym, "sell", qty=positions[sym].qty, reason="exit"))
                continue
            if not held:
                if delta >= min_trade:
                    orders.append(Order(sym, "buy", notional=round(delta, 2), reason="entry"))
                continue

            # existing holding: only adjust on material drift
            if abs(delta) < band:
                continue
            if delta > 0:
                orders.append(Order(sym, "buy", notional=round(delta, 2), reason="rebalance up"))
            elif price > 0:
                qty = min(positions[sym].qty, abs(delta) / price)
                orders.append(Order(sym, "sell", qty=round(qty, 6), reason="rebalance down"))
        return orders

    # ----------------------------------------------------------- stops
    def update_stops(self, state, positions: dict, data: dict[str, pd.DataFrame]):
        """Refresh trailing ATR stops; return list of symbols breaching their stop."""
        breached: list[str] = []
        live = set(positions)
        for sym in list(state.stops):
            if sym not in live:
                state.stops.pop(sym, None)
        for sym, pos in positions.items():
            if sym == self.cash_asset:
                continue
            df = data.get(sym)
            if df is None or len(df) < 20:
                continue
            a = atr(df, 14).iloc[-1]
            price = df["close"].iloc[-1]
            if pd.isna(a) or a <= 0 or not price:
                continue
            new_stop = price - self.stop_mult * a
            prev = state.stops.get(sym)
            # trailing: ratchet the stop up, never down
            state.stops[sym] = max(prev, new_stop) if prev else new_stop
            if price <= state.stops[sym]:
                breached.append(sym)
        return breached
