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

The strategy was chosen by **out-of-sample** validation over ~12 years of real data
(see `OPTIMIZATION_REPORT.md`). Default = `trend + mean_reversion + defensive`,
picked because it generalized best on data it was *not* tuned on.

**Full 11-year backtest** (the honest, un-cherry-picked picture):

| Metric | This bot | SPY buy & hold |
|---|---|---|
| Return (11 yr) | +41% (**~+3.2%/yr**) | +317% (~+13%/yr) |
| Sharpe (risk-adjusted) | **0.82** | ~0.6 |
| Max drawdown | **−6.4%** | ~−34% |
| % 2-week blocks negative | ~38% | — |

**Read this honestly:**
- This is a **capital-preserver, not a money printer.** ~+3%/yr with a tiny −6.4%
  max drawdown and a *better Sharpe than SPY* — but it **lags buy-and-hold badly**
  in bull markets (it sits in cash when trends weaken). That's the trade-off you
  asked for (minimize losses), made explicit.
- It is **positive and consistent out-of-sample** (Sharpe 0.62 on 2015–2023 which it
  was never tuned on, 1.28 on 2023–2026) — the optimization turned a *losing*
  baseline into a modestly profitable one. Honest, validated, not curve-fit.
- "No loss every 2 weeks" is **not** achieved (~38% of fortnights red) and cannot be
  guaranteed by anything. The weekly +1% target is rarely hit (~5% of weeks).
- These are *backtest* numbers. The future will differ. Your real numbers appear on
  the dashboard once it runs on Alpaca paper.

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

## Three ways to interact

| Surface | What it's for | How |
|---|---|---|
| **Public dashboard** (read-only) | See performance, positions, the agent's decisions, **+ market-research split-screen** (TradingView charts/news for any ticker). Always-on, shareable, no laptop. | GitHub Pages URL (`docs/`) |
| **Control panel** (interactive) | Pause/resume the bot, place manual trades, "ask the agent" why it's doing what it's doing, live account — **+ the same research split-screen**. Holds your keys locally, so it's secure. | `python control.py` → http://127.0.0.1:5001 |
| **Alpaca app** | Full manual trading / account management | app.alpaca.markets (Paper) |

> **Why controls aren't on the *public* dashboard:** placing trades needs your secret
> Alpaca key, which can't live in a public webpage (anyone could trade your account).
> So the control panel runs locally where your keys are safe. The autonomous bot still
> trades 24/7 in the cloud — the control panel is just your cockpit when you want to act.
> Pause/resume from it syncs to the cloud bot via `state/control.json`.

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

# View the read-only dashboard locally (after a run populates docs/data.json)
python -m http.server 8000 --directory docs    # then open http://127.0.0.1:8000

# INTERACTIVE control panel — view live account, pause/resume, place manual
# trades, "ask the agent", + market-research split-screen. Holds keys locally.
python control.py                              # then open http://127.0.0.1:5001

# Research / optimization (all offline once the cache is built)
python tools/build_data_cache.py            # download ~12y real data -> data/cache/
python backtest.py --source cache --years 12
python tools/compare_strategies.py          # in-sample vs out-of-sample per strategy
python optimize.py --mode holdout           # tune-on-past, test-on-held-out
python tools/ml_research.py                 # the (rejected) ML experiment

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
- `agent.use_sentiment` — optional **DeepSeek news-sentiment** tilt (off by default).
  Pulls recent headlines (Alpaca news API) → DeepSeek scores each ticker's sentiment →
  modestly tilts the allocation (capped, can't add leverage or override risk controls).
  Needs `DEEPSEEK_API_KEY`. **Experimental & unproven** — news-sentiment alpha is noisy;
  turn it on, run paper with it on vs off, and only keep it if the equity curve is
  genuinely better. (Same discipline that led me to reject the ML signal.)

---

## Project layout

```
config.yaml            # all behaviour/risk settings (config.growth.yaml = aggressive preset)
run.py                 # cron entrypoint (one cycle; --check validates setup)
backtest.py            # historical backtest CLI
optimize.py            # out-of-sample / walk-forward optimizer
OPTIMIZATION_REPORT.md # honest writeup of what was tried & validated
src/
  broker/              # Alpaca REST adapter + offline simulator
  strategies/          # trend, mean-reversion, defensive (+ momentum, dual_momentum off)
  agent/               # regime detection, performance-driven selector, controller
  risk/                # sizing, stops, halts, weekly/2-week rules
  engine.py            # one full decision/trade cycle (used live AND by backtest)
  backtester.py        # day-by-day backtest over the same engine
  evaluation.py        # walk-forward / holdout OOS harness
  telegram_bot.py      # optional Telegram interface (status / pause / resume)
  state.py             # persistent JSON state (equity, trades, decisions)
tools/                 # build_data_cache, compare_strategies, ml_research, validate_final
data/cache/            # cached real price history (parquet)
docs/                  # the GitHub Pages dashboard (index.html + generated data.json)
.github/workflows/     # the free scheduled-cron workflow
tests/                 # pytest suite
```

---

## Disclaimer

This is software for **educational and personal experimentation**, starting with paper
money. It is **not financial advice**, carries no guarantee of profit, and trading real
money risks real loss. You are responsible for your own account, keys, and decisions.
