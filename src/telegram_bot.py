"""Telegram bot — interact with Zimupaper from your phone.

Two ways it runs, both free:

  * **Push** — after each cron cycle, run.py sends a status update to your chat.
  * **Commands** — each cron cycle also pulls any commands you sent (via
    getUpdates) and replies. Because it piggybacks on the cron, replies land
    within one cron interval (~30 min). For real-time chat, run the poller
    locally:  ``python -m src.telegram_bot poll``

Built on the plain Telegram Bot API over ``requests`` — no extra dependency.

Commands: /status  /positions  /trades  /decisions  /pause  /resume  /help
State-changing commands (/pause, /resume) are only honoured from your own
configured chat id, so nobody else can control your bot.
"""
from __future__ import annotations

import os

API = "https://api.telegram.org/bot{token}/{method}"


# ----------------------------------------------------------------- transport
def _call(token: str, method: str, **params):
    import requests
    try:
        r = requests.post(API.format(token=token, method=method), json=params, timeout=20)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_message(token: str, chat_id, text: str) -> None:
    _call(token, "sendMessage", chat_id=chat_id, text=text, parse_mode="Markdown",
          disable_web_page_preview=True)


# ------------------------------------------------------------- message bodies
def _pct(x):
    return f"{x*100:+.2f}%"


def build_status(state, config) -> str:
    s = state
    lock = " 🔒banked" if s.week.locked else ""
    pause = "\n⏸️ *PAUSED* (send /resume to restart)" if s.manual_pause else ""
    halt = "\n⚠️ drawdown halt active" if s.drawdown_halted else ""
    return (
        f"*{config.account_label}* · {config.mode}\n"
        f"Equity: *${s.last_equity:,.0f}*\n"
        f"This week: *{_pct(s.weekly_return())}* / {_pct(config.weekly_gain)} target{lock}\n"
        f"2-week: {_pct(s.biweekly_return())}\n"
        f"Total: {_pct(s.total_return())}   Drawdown: {_pct(s.current_drawdown())}\n"
        f"Open positions: {len(s.last_positions)}{pause}{halt}"
    )


def build_positions(state) -> str:
    if not state.last_positions:
        return "Flat — no open positions (in cash)."
    lines = ["*Positions*"]
    for p in state.last_positions:
        lines.append(f"`{p['symbol']:<5}` {p['qty']:>8} @ ${p['price']}  = ${p['value']:,.0f}")
    return "\n".join(lines)


def build_trades(state, n=10) -> str:
    tr = state.trades[-n:][::-1]
    if not tr:
        return "No trades yet."
    lines = ["*Recent trades*"]
    for t in tr:
        lines.append(f"{t['t'][5:16]} {t['side']:<4} `{t['symbol']}` x{t['qty']} @ ${t['price']}")
    return "\n".join(lines)


def build_decisions(state, n=5) -> str:
    dec = state.decisions[-n:][::-1]
    if not dec:
        return "No decisions logged yet."
    lines = ["*Recent agent decisions*"]
    for d in dec:
        mix = ", ".join(f"{k} {v*100:.0f}%" for k, v in (d.get("strategies") or {}).items() if v > 0.01) or "cash"
        lines.append(f"{d['t'][5:16]} [{d['regime']}] {mix}")
    return "\n".join(lines)


HELP = ("*Zimupaper bot*\n"
        "/status — equity, weekly progress, drawdown\n"
        "/positions — current holdings\n"
        "/trades — recent fills\n"
        "/decisions — what the agent decided & why\n"
        "/pause — stop opening new trades\n"
        "/resume — resume trading\n"
        "/help — this message")


# --------------------------------------------------------------- command logic
def handle_command(text: str, state, config, *, authorized: bool) -> str:
    cmd = text.strip().split()[0].lstrip("/").lower().split("@")[0]
    if cmd in ("status", "start"):
        return build_status(state, config)
    if cmd == "positions":
        return build_positions(state)
    if cmd == "trades":
        return build_trades(state)
    if cmd == "decisions":
        return build_decisions(state)
    if cmd == "help":
        return HELP
    if cmd == "pause":
        if not authorized:
            return "Not authorized to change trading state."
        state.manual_pause = True
        return "⏸️ Trading *paused*. No new positions will be opened. Send /resume to restart."
    if cmd == "resume":
        if not authorized:
            return "Not authorized to change trading state."
        state.manual_pause = False
        return "▶️ Trading *resumed*."
    return f"Unknown command. {HELP}"


def process_updates(token: str, state, config, allowed_chat_id: str = "") -> int:
    """Pull pending Telegram commands, reply, advance the offset. Returns count handled."""
    if not token:
        return 0
    resp = _call(token, "getUpdates", offset=state.tg_offset + 1, timeout=0)
    if not resp.get("ok"):
        return 0
    handled = 0
    for upd in resp.get("result", []):
        state.tg_offset = max(state.tg_offset, upd["update_id"])
        msg = upd.get("message") or upd.get("edited_message")
        if not msg or "text" not in msg:
            continue
        chat_id = str(msg["chat"]["id"])
        authorized = (not allowed_chat_id) or (chat_id == str(allowed_chat_id))
        reply = handle_command(msg["text"], state, config, authorized=authorized)
        send_message(token, chat_id, reply)
        handled += 1
    return handled


def notify(token: str, chat_id: str, summary: dict) -> None:
    if not (token and chat_id):
        return
    text = (f"*Zimupaper* — {summary.get('action','?')}\n"
            f"Equity ${summary.get('equity'):,.0f} · "
            f"week {summary.get('weekly',0)*100:+.2f}% · "
            f"dd {summary.get('drawdown',0)*100:+.2f}%\n"
            f"_{summary.get('reason','')}_")
    send_message(token, chat_id, text)


# ------------------------------------------------------- real-time local poller
def poll(token: str, config, allowed_chat_id: str = "", interval: float = 2.0):
    """Long-poll for real-time interaction (run locally). Ctrl-C to stop."""
    import time

    from .state import State
    print("Polling Telegram… press Ctrl-C to stop.")
    while True:
        state = State.load()
        n = process_updates(token, state, config, allowed_chat_id)
        if n:
            state.save()
        time.sleep(interval)


def _main():
    import sys

    from .config import Config, Secrets
    secrets = Secrets.from_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN (and optionally TELEGRAM_CHAT_ID) in your .env first.")
        return 2
    config = Config.load()
    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        poll(token, config, chat)
    else:
        # one-shot: process pending commands once
        from .state import State
        st = State.load()
        n = process_updates(token, st, config, chat)
        if n:
            st.save()
        print(f"Handled {n} command(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
