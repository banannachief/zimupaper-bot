"""Optional market-sentiment overlay using DeepSeek — OFF by default.

Flow: pull recent headlines (Alpaca news API, free) -> ask DeepSeek to score each
ticker's sentiment in [-1, +1] -> use it to *tilt* the allocation the strategies
already chose. It is strictly an overlay: it can trim or modestly boost existing
positions, but it can never introduce leverage, new tickers beyond the universe,
or override the risk manager (stops/halts/sizing all still apply afterwards).

Enable with `agent.use_sentiment: true` in config AND a DEEPSEEK_API_KEY in the
environment. Without either, sentiment is neutral and changes nothing.

HONESTY: news-sentiment alpha in liquid ETFs is unproven and noisy. This ships
OFF and capped (small tilt) on purpose. Treat it as experimental — validate it
on paper (compare equity curves with it on vs off) before trusting it, exactly
like the ML signal that was tested and rejected.
"""
from __future__ import annotations

import json
import os

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

_SYS = (
    "You are a financial news sentiment analyst. For each ticker, judge whether "
    "the headlines are net bullish or bearish for its price over the next 1-2 weeks. "
    "Score each ticker from -1.0 (very bearish) to +1.0 (very bullish), 0 if neutral "
    "or no relevant news. Respond ONLY with a JSON object mapping ticker -> number."
)


def analyze(news: list[dict], universe: list[str], *, api_key: str | None = None,
            model: str = "deepseek-chat", timeout: int = 30) -> dict[str, float]:
    """Return {ticker: sentiment in [-1,1]}. Empty dict on any failure (safe)."""
    api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key or not news:
        return {}

    # group headlines by ticker (cap to keep the prompt small)
    by_sym: dict[str, list[str]] = {}
    for item in news:
        line = item.get("headline", "").strip()
        if not line:
            continue
        for s in item.get("symbols", []):
            if s in universe and len(by_sym.get(s, [])) < 6:
                by_sym.setdefault(s, []).append(line)
    if not by_sym:
        return {}

    blob = "\n".join(f"{s}:\n  - " + "\n  - ".join(h) for s, h in by_sym.items())
    try:
        import requests
        r = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "system", "content": _SYS},
                             {"role": "user", "content": blob}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0, "max_tokens": 400,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        raw = json.loads(content)
    except Exception:
        return {}

    out: dict[str, float] = {}
    for s, v in raw.items():
        if s in universe:
            try:
                out[s] = max(-1.0, min(1.0, float(v)))
            except (TypeError, ValueError):
                continue
    return out


def apply_tilt(weights: dict[str, float], sentiment: dict[str, float],
               strength: float, cash_asset: str = "BIL") -> dict[str, float]:
    """Tilt existing target weights by sentiment, keeping gross exposure constant.

    * strongly negative sentiment (<= -0.5) -> drop the name to cash,
    * otherwise scale weight by (1 + strength * score), clamped non-negative,
    * renormalize risk weights back to the original gross (no added leverage).
    """
    if not sentiment or strength <= 0:
        return weights
    risk = {s: w for s, w in weights.items() if s != cash_asset and w > 0}
    if not risk:
        return weights
    orig_gross = sum(risk.values())
    tilted = {}
    for s, w in risk.items():
        score = sentiment.get(s, 0.0)
        if score <= -0.5:
            continue                       # bail out of clearly-bearish names
        tilted[s] = max(0.0, w * (1.0 + strength * score))
    new_gross = sum(tilted.values())
    out = {s: w for s, w in weights.items() if s == cash_asset}
    if new_gross > 0:
        scale = orig_gross / new_gross     # preserve total exposure
        for s, w in tilted.items():
            out[s] = w * scale
    else:
        # everything was filtered out (all bearish) -> park the freed capital in cash
        out[cash_asset] = out.get(cash_asset, 0.0) + orig_gross
    return out
