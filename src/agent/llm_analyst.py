"""Optional Claude-powered "portfolio analyst" — OFF by default.

This is an *advisory* layer. It reviews the regime + the controller's proposed
allocation and may suggest scaling overall risk exposure DOWN (never up beyond
the controller's plan). The deterministic risk manager still has final veto, so
the LLM can never bypass a stop-loss, a halt, or the position-size caps.

Enable by setting `agent.use_llm_analyst: true` in config.yaml AND providing
ANTHROPIC_API_KEY. Requires `pip install anthropic`. The model defaults to
claude-opus-4-8 (override with `agent.llm_model`, e.g. claude-haiku-4-5 to cut
cost on frequent runs).
"""
from __future__ import annotations

import json

_SCHEMA = {
    "type": "object",
    "properties": {
        "exposure_scale": {
            "type": "number",
            "description": "Multiplier in [0.3, 1.0] applied to all risk-asset "
                           "weights. 1.0 = keep the plan, lower = de-risk.",
        },
        "rationale": {"type": "string", "description": "One sentence, <=160 chars."},
    },
    "required": ["exposure_scale", "rationale"],
    "additionalProperties": False,
}


def advise(target_weights: dict[str, float], regime, scores: dict, config):
    """Return (possibly_adjusted_weights, note). Never raises out — fail safe."""
    import os

    from anthropic import Anthropic  # local import; optional dependency

    if not os.getenv("ANTHROPIC_API_KEY"):
        return target_weights, "no ANTHROPIC_API_KEY"

    model = config.agent.get("llm_model", "claude-opus-4-8")
    summary = {
        "regime": {"label": regime.label, "vol": round(regime.vol, 3),
                   "risk_budget": regime.risk_budget},
        "strategy_scores": {k: round(v, 3) for k, v in scores.items()},
        "proposed_weights": {k: round(v, 3) for k, v in target_weights.items()},
        "weekly_target": config.weekly_gain,
    }
    system = (
        "You are a risk-first portfolio analyst for a systematic US-equity bot. "
        "You may only recommend REDUCING risk exposure when conditions look "
        "dangerous (stretched, high-vol, deteriorating). You cannot add leverage "
        "or new tickers. Respond with exposure_scale in [0.3, 1.0]."
    )
    client = Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=400,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(summary)}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    data = json.loads(text)
    scale = float(data.get("exposure_scale", 1.0))
    scale = max(0.3, min(1.0, scale))
    cash_asset = config.cash_asset
    adjusted = {}
    for sym, w in target_weights.items():
        adjusted[sym] = w if sym == cash_asset else w * scale
    note = f"scale={scale:.2f} ({data.get('rationale', '')[:120]})"
    return adjusted, note
