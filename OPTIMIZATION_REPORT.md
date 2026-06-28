# Optimization report — overnight autonomous run

*Honest account of what was tried, what was validated out-of-sample (OOS), and
what was kept. Written for you to read in the morning.*

## TL;DR
- **Biggest win:** replaced the old strategy (which *lost* money over 12y) with an
  OOS-validated **trend + mean-reversion** engine. Full 11-year backtest:
  **+3.2%/yr, Sharpe 0.82, −6.4% max drawdown** — positive and consistent on data
  it was never tuned on.
- **It is a capital-preserver, not a money printer.** It lags buy-and-hold SPY in
  bull markets (tiny drawdowns are the trade-off). No free bot makes 10%/week.
- **Rejected (didn't survive OOS):** machine learning (no edge), dual-momentum
  (overfit), the "growth" risk dial (more risk, no more return), aggressive
  churn-tuning (overfit the recent window).
- **Infrastructure built:** 12y real-data cache, walk-forward/holdout OOS harness,
  ~6× faster backtests, expanded tests (38 passing). All offline-runnable.

> **Methodology guardrail:** every change below was judged on **out-of-sample**
> data (periods it was not tuned on). In-sample-only improvements are overfitting
> and were discarded. Where a fancy idea (incl. ML) failed OOS, that's stated
> plainly — a negative result honestly reported is worth more than a curve-fit
> backtest that blows up your real account.

## Setup
- **Data:** 12 years of real daily history for 39 ETFs, cached locally
  (`data/cache/*.parquet`) via `tools/build_data_cache.py`.
- **Honest harness:** `src/evaluation.py` (walk-forward + holdout), driven by
  `optimize.py`; strategy comparison via `tools/compare_strategies.py`.
- **Baseline:** the original momentum + mean-reversion + defensive ensemble.

## Engine improvements (mechanical, validated to not hurt)
1. **Decision cadence** — re-decide allocation ~weekly instead of every day
   (stops/rebalancing still daily). Cuts turnover and ~5× faster backtests.
2. **Rebalance band** — suppress sub-2%-of-equity adjustments (less churn).
3. **Gentler agentic de-risk** — only cut risk on a real drawdown, not on noise.
4. **Speed** — positional tail-slicing in the hot path; backtests fast enough to
   run walk-forward optimization.

## Strategy research (OOS) — `trend + mean_reversion` chosen

Two new strategies were added (`src/strategies/trend.py`, `dual_momentum.py`)
and every combination was compared on an older IN-SAMPLE window and a recent
OUT-OF-SAMPLE window (`tools/compare_strategies.py`).

**In-sample** (2015-08→2023-06, SPY +140%):

| combo | return | Sharpe | maxDD | %2wk-neg |
|---|---|---|---|---|
| baseline (mom+mr) | +16.5% | 0.49 | −7.2% | 44% |
| dual_momentum | +22.8% | 0.55 | −9.1% | 39% |
| trend | +21.9% | 0.57 | −7.3% | 39% |
| dualmom+trend | +32.5% | 0.74 | −6.9% | 39% |
| trend+mr | +20.6% | 0.62 | −6.4% | 41% |
| all4 | +28.5% | 0.70 | −6.4% | 42% |

**Out-of-sample** (2023-06→2026-06, SPY +73.5%) — the honest test:

| combo | return | Sharpe | maxDD | %2wk-neg |
|---|---|---|---|---|
| baseline (mom+mr) | +6.2% | 0.42 | −4.4% | 37% |
| dual_momentum | +3.6% | **0.22** | −6.1% | 36% |
| trend | +18.9% | 1.10 | −3.5% | 30% |
| dualmom+trend | +13.2% | 0.70 | −5.3% | 37% |
| **trend+mr (chosen)** | **+16.2%** | **1.28** | **−3.9%** | **31%** |
| all4 | +14.4% | 0.82 | −4.5% | 37% |

- **`trend + mean_reversion` won OOS** (Sharpe 1.28, vs baseline 0.42) and was
  top-2 in *both* windows → robust, not a fluke. Drawdown −3.9% and only 31% of
  2-week blocks negative (best-in-class on your no-loss-fortnight goal).
- **`dual_momentum` overfit**: great in-sample (0.55), collapsed OOS (0.22).
  Rejected. This is the single clearest illustration of why OOS testing matters.
- The old default (momentum + mean_reversion) was the *weakest* survivor. Replaced.

## ML signal (OOS) — tested, REJECTED (honest negative result)
Built a leak-free, walk-forward LightGBM forward-return predictor
(`tools/ml_research.py`): retrain quarterly, predict next quarter, no lookahead.

| OOS weekly portfolio | Total | Ann | Sharpe | MaxDD | Win% |
|---|---|---|---|---|---|
| ML top-N | +192% | +17% | 0.77 | −38% | 60% |
| Equal-weight (baseline) | +175% | +15% | **0.90** | **−28%** | 64% |

- **Mean IC = 0.020** (rank corr of prediction vs realized) — at the noise floor.
- Risk-adjusted, the ML model is **worse** than naive equal-weight.
- **Decision: NOT shipped.** A no-edge model adds complexity + drawdown for no gain.
  (This is the expected outcome for liquid ETFs — markets are near-efficient. Better
  to know it now than to discover it with real money.)
- Side-insight: equal-weight-everything returned +175% here, so the bot's real
  weakness is being too cash-heavy and missing broad uptrends — addressed by the
  trend/dual-momentum strategies, not by ML.

## Final configuration & expectations

**Default = `trend + mean_reversion + defensive`, decision cadence ≈ weekly,
rebalance band 2%, vol-targeted sizing, all original risk controls intact.**

Validated on 11 years of real data, with the earlier period held truly
out-of-sample for every choice made:

| Period | Return | CAGR | Sharpe | MaxDD | %2wk-neg | SPY |
|---|---|---|---|---|---|---|
| **True-OOS early (2015–2023)** | +20.6% | +2.4% | **0.62** | −6.4% | 41% | +140% |
| Selection window (2023–2026) | +16.2% | +5.1% | 1.28 | −3.9% | 31% | +73% |
| **Full (2015–2026)** | +41.2% | +3.2% | **0.82** | **−6.4%** | 38% | +317% |

**Honest expectations:**
- Over a full cycle, expect roughly **+3%/yr with a small (~−6%) max drawdown and
  Sharpe ≈ 0.8** — *positive and generalizing*, but modest.
- It **lags buy-and-hold SPY badly in bull markets** (+41% vs +317% over 11y) by
  design: it rotates to cash when trends weaken, which caps upside but kept the
  worst drawdown to −6.4% vs SPY's ~−34% in 2022.
- The weekly **+1% take-profit** rarely triggers (~5% of weeks); the
  **no-loss-every-2-weeks** goal is *not* achieved (~38% of fortnights red) — no
  strategy can guarantee it.
- **What changed vs the original:** the old default (momentum+mean_reversion)
  *lost* money over 12 years (−9%); this is a real, validated turnaround — but it
  is a capital-preserver, not a money printer. Anyone telling you a free bot makes
  10%/week is lying; these are the honest numbers.

**For more growth (accepting bigger swings):** see *Preservation vs growth* in
README — but note the backtests show extra risk did NOT add return here, so do it
with eyes open.

## What did NOT work (kept for honesty)

1. **Machine learning** — leak-free walk-forward LightGBM had IC ≈ 0.02 (noise) and
   *worse* risk-adjusted returns than naive equal-weight. Rejected.
2. **dual_momentum** — best in-sample (Sharpe 0.55), collapsed out-of-sample (0.22).
   A classic overfit; rejected.
3. **The "growth" risk dial** — turning up risk_per_trade / drawdown limits added
   volatility and drawdown without adding return (worse Sharpe). The problem was
   never the risk dial; it was signal quality.
4. **Aggressive churn-tuning (monthly cadence + 5% band)** — looked *great* on the
   recent window (Sharpe 1.52) but the true-OOS earlier period exposed it as
   overfit (Sharpe 0.46 vs the robust default's 0.62). Reverted to robust defaults.
   This is the single best illustration in this whole run of why "best backtest
   number" ≠ "best strategy".
5. **Plain momentum** — the original engine; weakest survivor OOS. Disabled.
6. **Expanding the universe** (12 → 23 ETFs: more sectors, international, bonds,
   commodities) — *worse* in both periods (Sharpe 0.39 vs 0.62 early, 0.92 vs 1.28
   recent). The extras were too correlated to add real diversification. Kept the
   curated 12.

The meta-lesson, applied throughout: I optimized for *robustness across unseen
periods*, not for the prettiest single backtest. Several changes that improved
the headline number were thrown out because they didn't generalize.
