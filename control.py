#!/usr/bin/env python3
"""Zimupaper LOCAL control panel.

A small Flask app you run on your own machine to interact with the bot from a
browser — the dashboard-based replacement for Telegram. It holds your Alpaca
keys locally (from .env) and NEVER exposes them to the page, so it's safe in a
way a public webpage can't be. It can:

  * show your LIVE account + positions (real-time from Alpaca),
  * Pause / Resume the bot (writes state/control.json; the cloud bot obeys it
    on its next run — push it with the button or your next git push),
  * place manual Buy / Sell orders (optionally auto-pausing the bot first),
  * Flatten everything,
  * "Ask the agent" — it explains, in plain language, what it would do right now
    and why (regime, which strategy, target allocation),
  * embed the same TradingView market-research split-screen.

Run:  python control.py     then open  http://127.0.0.1:5001
The autonomous bot keeps trading in the cloud regardless; this is just your
cockpit for when you want to look or act.
"""
from __future__ import annotations

import json
import os
import subprocess

from flask import Flask, jsonify, request

from src.agent.controller import Controller
from src.broker import make_broker
from src.config import Config, Secrets
from src.state import State
from src.strategies import build_strategies

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL_PATH = os.path.join(ROOT, "state", "control.json")

app = Flask(__name__)
_cfg = Config.load()
_sec = Secrets.from_env()


def _broker():
    return make_broker(_cfg, _sec)


def _write_control(pause: bool, push: bool = False) -> dict:
    os.makedirs(os.path.dirname(CONTROL_PATH), exist_ok=True)
    with open(CONTROL_PATH, "w", encoding="utf-8") as fh:
        json.dump({"manual_pause": pause}, fh, indent=2)
    pushed = False
    if push:
        try:
            subprocess.run(["git", "-C", ROOT, "add", "state/control.json"], check=True,
                           capture_output=True, timeout=30)
            subprocess.run(["git", "-C", ROOT, "-c", "user.name=zimupaper-control",
                            "-c", "user.email=control@local", "commit", "-m",
                            f"control: manual_pause={pause}"], check=True,
                           capture_output=True, timeout=30)
            subprocess.run(["git", "-C", ROOT, "push", "origin", "main"], check=True,
                           capture_output=True, timeout=90)
            pushed = True
        except Exception:
            pushed = False
    return {"manual_pause": pause, "pushed_to_cloud": pushed}


# --------------------------------------------------------------------- API
@app.get("/api/account")
def api_account():
    try:
        a = _broker().get_account()
        return jsonify(ok=True, equity=a.equity, cash=a.cash,
                       buying_power=a.buying_power, last_equity=a.last_equity)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])


@app.get("/api/positions")
def api_positions():
    try:
        pos = _broker().get_positions()
        return jsonify(ok=True, positions=[
            {"symbol": p.symbol, "qty": round(p.qty, 4),
             "price": round(p.current_price, 2), "value": round(p.market_value, 2),
             "avg": round(p.avg_entry_price, 2)} for p in pos.values()])
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])


def _control_paused() -> bool:
    try:
        with open(CONTROL_PATH, "r", encoding="utf-8") as fh:
            return bool(json.load(fh).get("manual_pause", False))
    except Exception:
        return False


@app.get("/api/state")
def api_state():
    st = State.load()
    return jsonify(ok=True, paused=_control_paused(),
                   equity_curve=st.equity_curve[-400:], decisions=st.decisions[-30:][::-1],
                   strategy_mix=st.last_strategy_weights or {},
                   weekly=st.weekly_return(), total=st.total_return(),
                   drawdown=st.current_drawdown())


@app.post("/api/pause")
def api_pause():
    push = bool((request.json or {}).get("push", True))
    return jsonify(ok=True, **_write_control(True, push))


@app.post("/api/resume")
def api_resume():
    push = bool((request.json or {}).get("push", True))
    return jsonify(ok=True, **_write_control(False, push))


@app.post("/api/order")
def api_order():
    body = request.json or {}
    sym = str(body.get("symbol", "")).upper().strip()
    side = str(body.get("side", "buy")).lower()
    notional = body.get("notional")
    qty = body.get("qty")
    if not sym or side not in ("buy", "sell"):
        return jsonify(ok=False, error="need symbol and side=buy|sell")
    if body.get("auto_pause"):
        _write_control(True, push=False)
    try:
        b = _broker()
        if side == "sell" and (notional in (None, "", 0)) and (qty in (None, "", 0)):
            res = b.close_position(sym)             # sell with no size = close out
        else:
            kw = {}
            if notional not in (None, "", 0):
                kw["notional"] = float(notional)
            elif qty not in (None, "", 0):
                kw["qty"] = float(qty)
            res = b.submit_order(sym, side, **kw)
        return jsonify(ok=res.ok, note=res.note, filled_qty=res.filled_qty,
                       avg_price=res.avg_price)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])


@app.post("/api/flatten")
def api_flatten():
    try:
        results = _broker().close_all()
        return jsonify(ok=True, results=[{"symbol": r.symbol, "ok": r.ok, "note": r.note}
                                         for r in results])
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])


@app.get("/api/explain")
def api_explain():
    """The agent explains what it would do right now, and why."""
    try:
        b = _broker()
        data = b.get_bars(_cfg.all_symbols, _cfg.data.get("timeframe", "1Day"),
                          int(_cfg.data.get("history_bars", 320)))
        ctrl = Controller(build_strategies(_cfg), _cfg)
        dec = ctrl.decide(data, State.load())
        tw = {k: round(v, 3) for k, v in dec.target_weights.items() if v > 0.01}
        sw = {k: round(v, 3) for k, v in dec.strategy_weights.items() if v > 0.01}
        plain = (f"Market regime looks **{dec.regime.label}** ({dec.regime.note}). "
                 f"Strategy mix: {sw or 'all cash'}. "
                 f"Target holdings: {tw or 'cash (no positions)'}. "
                 f"Reasoning: {dec.note}")
        return jsonify(ok=True, regime=dec.regime.label, strategy_weights=sw,
                       target_weights=tw, note=dec.note, plain=plain)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])


@app.get("/")
def index():
    return CONTROL_HTML


CONTROL_HTML = open(os.path.join(ROOT, "control.html"), encoding="utf-8").read() \
    if os.path.exists(os.path.join(ROOT, "control.html")) else "<h1>control.html missing</h1>"


if __name__ == "__main__":
    port = int(os.getenv("CONTROL_PORT", "5001"))
    print(f"\n  Zimupaper control panel -> http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
