#!/usr/bin/env python3
"""Cron entrypoint — runs ONE trading cycle, then exits.

GitHub Actions calls this on a schedule during market hours. It loads config +
secrets, talks to the broker (Alpaca paper by default), runs the engine, updates
state + the dashboard data, and optionally posts a Discord alert.

Usage:
    python run.py                 # one live cycle (uses config.yaml + .env)
    python run.py --check         # validate keys/config/broker connection, then exit
    python run.py --broker sim    # offline dry-run, no keys needed
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from src.broker import make_broker
from src.config import Config, Secrets
from src.engine import run_cycle
from src.state import State


def notify_discord(webhook: str, summary: dict) -> None:
    if not webhook:
        return
    try:
        import requests
        msg = (f"**Zimupaper** {summary.get('action','?').upper()} | "
               f"equity ${summary.get('equity')} | week {summary.get('weekly',0)*100:+.2f}% | "
               f"dd {summary.get('drawdown',0)*100:+.2f}% | {summary.get('reason','')}")
        requests.post(webhook, json={"content": msg}, timeout=10)
    except Exception as e:
        print(f"(discord notify failed: {e})")


def preflight(config, secrets) -> int:
    """Validate setup before trusting the bot. `python run.py --check`."""
    ok = "[ OK ]"
    no = "[FAIL]"
    warn = "[WARN]"
    print("=" * 54)
    print("  Zimupaper preflight check")
    print("=" * 54)
    print(f"  mode: {config.mode} | broker: {config.broker} | "
          f"weekly target: {config.weekly_gain*100:.1f}%")
    print(f"  universe: {len(config.universe)} symbols | benchmark: {config.benchmark}")
    print("-" * 54)

    problems = 0
    # Alpaca keys
    if secrets.has_alpaca:
        print(f"  {ok}  Alpaca API keys found")
        is_live = "paper" not in secrets.alpaca_base_url
        print(f"        endpoint: {secrets.alpaca_base_url} "
              f"({'LIVE — real money!' if is_live else 'paper'})")
        try:
            from src.broker.alpaca import AlpacaBroker
            acct = AlpacaBroker(secrets).get_account()
            print(f"  {ok}  Connected to Alpaca — equity ${acct.equity:,.2f}, "
                  f"cash ${acct.cash:,.2f}")
        except Exception as e:
            print(f"  {no}  Could not reach Alpaca: {e}")
            problems += 1
    else:
        print(f"  {warn} No Alpaca keys (set ALPACA_API_KEY/SECRET in .env or "
              f"GitHub Secrets). Offline 'sim' broker still works.")
        problems += 1

    # Optional integrations
    print(f"  {ok if secrets.telegram_token else warn}  Telegram "
          f"{'configured' if secrets.telegram_token else 'not configured (optional)'}")
    print(f"  {ok if secrets.anthropic_key else warn}  Claude analyst key "
          f"{'present' if secrets.anthropic_key else 'absent (optional, off by default)'}")
    print("-" * 54)
    if problems == 0:
        print("  All good — you're ready to trade. Run:  python run.py")
    else:
        print(f"  {problems} item(s) need attention (see above). The bot can still")
        print("  run offline with:  python run.py --broker sim")
    print("=" * 54)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--broker", default=None, help="override broker (alpaca|sim)")
    ap.add_argument("--no-render", action="store_true", help="skip dashboard render")
    ap.add_argument("--check", action="store_true",
                    help="validate config + keys + broker connection, then exit")
    args = ap.parse_args()

    config = Config.load(args.config)
    if args.broker:
        config.raw["broker"] = args.broker
    secrets = Secrets.from_env()

    if args.check:
        return preflight(config, secrets)

    try:
        broker = make_broker(config, secrets)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 2

    state = State.load()
    summary = run_cycle(broker, config, state, render=not args.no_render, persist=True)

    print(json.dumps(summary, indent=2, default=str))
    notify_discord(secrets.discord_webhook or os.getenv("DISCORD_WEBHOOK_URL", ""), summary)

    # Telegram: push the summary, then process any commands the user sent.
    if secrets.telegram_token:
        from src.telegram_bot import notify as tg_notify, process_updates
        tg_notify(secrets.telegram_token, secrets.telegram_chat, summary)
        handled = process_updates(secrets.telegram_token, state, config, secrets.telegram_chat)
        if handled:
            state.save()
            print(f"Handled {handled} Telegram command(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
