# Zimupaper — an agentic, self-adjusting trading bot

A free, cloud-hosted US-equity/ETF trading bot that:

- **runs for free** on GitHub Actions (a scheduled cron — no server, no credit card),
- trades through **Alpaca** (paper money first, real money later — one config flip),
- is **agentic**: a meta-controller scores its own strategies on recent performance,
  rotates capital toward what's working, detects the market regime, and **flees to cash
  when nothing is working** — i.e. it adjusts its own algorithm,
- **banks the week and stops** once it's up **+1%** (your weekly take-profit target),
- actively **defends a non-negative close every 2 weeks**,
- enforces **hard risk limits** (per-trade sizing, stop-losses, daily-loss halt, max-drawdown halt),
- ships an **interactive web dashboard** (free GitHub Pages) **and an optional Telegram bot**
  (check status / positions / pause-resume trading from your phone).

> ### ⚠️ Read this first — honest expectations
> No algorithm can *guarantee* positive returns. The **+1%/week** figure is a
> **take-profit target the bot stops at when it gets there**, not a floor it hits every
> week. Some weeks it will make less, break even, or lose. "No losses every 2 weeks" is
> enforced by de-risking rules that make losing 2-week closes *rare* — not impossible
> (overnight gaps exist). **That is exactly why we start on paper money.** Prove it on
> fake money, watch the real weekly distribution on the dashboard, and only move to real
> funds if the numbers justify it. Nothing here is financial advice.

---

## What the backtest actually shows (real data, honest)

3 years of real market data (2023-05 → 2026-06), default "preservation" config:

| Metric | Result |
|---|---|
| Total return (3 yr) | **+7.6%** (~+2.4%/yr) |
| Benchmark SPY (buy & hold) | +84.3% |
| Max drawdown | **−4.4%** (very small) |
| % weeks that hit the +1% target | 5.5% |
| % 2-week blocks that closed negative | ~41% |

**Read this honestly:** the bot is tuned for *capital preservation* — tiny drawdowns,
small steady participation — so it **lags a strong bull market badly**, and the
"no loss every 2 weeks" aim is an *aspiration the risk rules push toward, not a
guarantee they achieve* (~41% of 2-week blocks still closed slightly red in backtest).
A bot can chase the market's big upside **or** keep drawdowns tiny — not both. You decide
the trade-off (see *Preservation vs growth* below). Past results never predict the future;
your real numbers will appear on the dashboard once it's live on Alpaca paper.

---

## Preservation vs growth

The default config is **preservation-first** (the mandate you gave: minimize losses, bank
+1% and stop). If you'd rather pursue more upside and accept bigger swings, edit
`config.yaml`:

| Knob | Preservation (default) | More growth |
|---|---|---|
| `targets.weekly_gain` | `0.01` | `0.02`–`0.03` (or remove to ride trends) |
| `risk.risk_per_trade` | `0.01` | `0.02` |
| `risk.max_drawdown_halt` | `0.10` | `0.20` |
| `agent.underperform_drawdown` | `0.03` | `0.06` (de-risk less often) |

Re-run `python backtest.py --source yfinance` after changing — it's free and instant.

---

## How it works (the short version)

```
GitHub Actions (cron, free)
        │  every 30 min during US market hours
        ▼
   run.py ──► engine.run_cycle
                 │
                 ├─ broker (Alpaca paper/live)  ── account, prices, orders
                 ├─ agent  (regime + strategy selector)  ── "what's working now?"
                 ├─ risk   (sizing, stops, weekly +1% TP, 2-week defense, halts)
                 └─ state  (equity curve, trades, decisions) ─► docs/data.json
                                                                     │
                                                       GitHub Pages dashboard
```

The **agent** keeps three strategies — momentum/trend (risk-on), mean-reversion
(range-bound), and defensive (cash-like T-bill ETF) — and every run it "shadow-trades"
each one over the recent window, scores them, and allocates toward the winners. If none
are working, it parks in cash. The **risk manager** always has the final word over the
agent: it caps position sizes by volatility, sets trailing stops, halts on big losses,
and liquidates to bank the week once +1% is hit.

---

## ✅ Setup checklist (~10 minutes, one time)

You do these once; after that the bot runs itself for free. I (the code) can't create
accounts or generate keys for you — those need your identity — so here's the exact path.

### 1. Create the Alpaca paper-trading account ("Zimupaper")

1. Go to **https://alpaca.markets** → **Sign up** (free). Use it as your *Zimupaper* account.
2. After signing in, switch to **Paper Trading** (toggle in the dashboard — it starts you
   with $100,000 of fake money).
3. Open **Home → API Keys** (or "Generate New Keys") under the *paper* account.
4. Copy the **API Key ID** and the **Secret Key** somewhere safe (the secret is shown once).

### 2. Put this project on GitHub

1. Create a **new GitHub repository** (private is fine).
2. Push this folder to it:
   ```bash
   git init
   git add .
   git commit -m "Zimupaper trading bot"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```

### 3. Add your keys as GitHub Secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add these three (names must match exactly):

| Secret name         | Value                                            |
|---------------------|--------------------------------------------------|
| `ALPACA_API_KEY`    | your paper **API Key ID**                         |
| `ALPACA_API_SECRET` | your paper **Secret Key**                          |
| `ALPACA_BASE_URL`   | `https://paper-api.alpaca.markets`                |

*(Optional: `ANTHROPIC_API_KEY` to enable the LLM analyst, `DISCORD_WEBHOOK_URL` for alerts,
and the Telegram pair below.)*

### 3b. (Optional) Telegram bot — control it from your phone

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the **bot token**.
2. Message **@userinfobot** to get your numeric **chat id**.
3. Add two more GitHub Secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

Then message your bot: `/status`, `/positions`, `/trades`, `/decisions`, `/pause`, `/resume`.
Replies arrive within one cron interval (~30 min) since command handling piggybacks on the
schedule. For real-time chat, run the poller locally: `python -m src.telegram_bot poll`.
`/pause` and `/resume` are only honoured from *your* chat id, so nobody else can control it.

### 4. Turn on the free dashboard (GitHub Pages)

**Settings → Pages → Build and deployment → Source: Deploy from a branch →
Branch: `main`, folder: `/docs` → Save.**
Your dashboard will be live at `https://<you>.github.io/<repo>/`. It populates after the
first bot run.

### 5. Run it

- It runs **automatically** on the schedule (every 30 min during US market hours).
- To run it **now**: repo → **Actions → "Zimupaper trading bot" → Run workflow**.
- After it runs, it commits updated `state/` + `docs/` and the dashboard updates.

That's it. The bot is now trading paper money on the cloud, for free, and reporting to
your dashboard.

---

## Run it locally (optional)

```bash
pip install -r requirements.txt

# Verify your keys + config + Alpaca connection are working (do this first)
python run.py --check

# Backtest the whole stack on history (validates the logic before paper trading)
python backtest.py --source yfinance --years 3      # real data
python backtest.py --source synthetic               # offline, no network

# Dry-run one cycle with no broker keys (offline simulator)
python run.py --broker sim

# One real paper cycle locally (needs a .env — copy .env.example to .env first)
python run.py

# Tests
python -m pytest -q
```

Open `docs/index.html` in a browser to view the dashboard locally.

---

## Going live with real money (later — only after paper proves out)

1. Fund your Alpaca account and switch it from paper to **live**.
2. Generate **live** API keys, and update the GitHub Secrets:
   - `ALPACA_API_KEY` / `ALPACA_API_SECRET` → your **live** keys
   - `ALPACA_BASE_URL` → `https://api.alpaca.markets`
3. In `config.yaml`, set `mode: live`.
4. Start small. The same risk limits apply, but losses are now real.

The dashboard banner turns red in live mode so you always know which money is at risk.

---

## Configuration

Everything tunable lives in **`config.yaml`** — universe, the +1% weekly target, risk
limits (per-trade risk, max drawdown halt, stop distance), and strategy parameters. No
code changes needed; edit and the next run picks it up. Key knobs:

- `targets.weekly_gain` — the weekly take-profit (default `0.01` = +1%).
- `risk.max_drawdown_halt` — go to cash & re-strategize past this drawdown (default 10%).
- `risk.risk_per_trade` / `risk.max_weight_per_name` — position sizing caps.
- `agent.use_llm_analyst` — optional Claude advisory layer (off by default).

---

## Project layout

```
config.yaml            # all behaviour/risk settings
run.py                 # cron entrypoint (one cycle)
backtest.py            # historical backtest CLI
src/
  broker/              # Alpaca REST adapter + offline simulator
  strategies/          # momentum, mean-reversion, defensive
  agent/               # regime detection, performance-driven selector, controller
  risk/                # sizing, stops, halts, weekly/2-week rules
  engine.py            # one full decision/trade cycle (used live AND by backtest)
  backtester.py        # vectorized walk-forward over the same engine
  telegram_bot.py      # optional Telegram interface (status / pause / resume)
  state.py             # persistent JSON state (equity, trades, decisions)
docs/                  # the GitHub Pages dashboard (index.html + generated data.json)
.github/workflows/     # the free scheduled-cron workflow
tests/                 # pytest suite
```

---

## Disclaimer

This is software for **educational and personal experimentation**, starting with paper
money. It is **not financial advice**, carries no guarantee of profit, and trading real
money risks real loss. You are responsible for your own account, keys, and decisions.
