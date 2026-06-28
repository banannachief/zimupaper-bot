"""Render the dashboard data file the static page reads.

Writes ``dashboard/data.json`` from the persistent State. The page (index.html)
is static and fetches this JSON, so the dashboard updates automatically every
time the bot commits a new state.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
# Output dir is "docs/" so GitHub Pages can serve it directly from the main
# branch (Settings -> Pages -> Deploy from branch -> main /docs).
DASH_DIR = ROOT / "docs"


def _downsample(rows: list, max_points: int = 750) -> list:
    if len(rows) <= max_points:
        return rows
    step = len(rows) / max_points
    return [rows[int(i * step)] for i in range(max_points)] + [rows[-1]]


def render_dashboard(state, config, path: Path | None = None,
                     preview: bool = False) -> Path:
    DASH_DIR.mkdir(parents=True, exist_ok=True)
    out = path or (DASH_DIR / "data.json")

    equity = _downsample(state.equity_curve)

    # normalize benchmark to start at the same equity (for a fair overlay)
    bench = state.benchmark_curve
    bench_norm = []
    if bench and state.starting_equity > 0:
        base = next((b["value"] for b in bench if b.get("value")), None)
        if base:
            bench_norm = _downsample(
                [{"t": b["t"], "value": round(b["value"] / base * state.starting_equity, 2)}
                 for b in bench if b.get("value")]
            )

    data = {
        "account_label": config.account_label,
        "mode": config.mode,
        "preview": preview,
        "updated_at": state.updated_at,
        "weekly_target": config.weekly_gain,
        "summary": {
            "starting_equity": round(state.starting_equity, 2),
            "equity": round(state.last_equity, 2),
            "peak_equity": round(state.peak_equity, 2),
            "total_return": round(state.total_return(), 4),
            "weekly_return": round(state.weekly_return(), 4),
            "biweekly_return": round(state.biweekly_return(), 4),
            "drawdown": round(state.current_drawdown(), 4),
            "week_start_equity": round(state.week.start_equity, 2),
            "week_locked": state.week.locked,
            "biweek_start_equity": round(state.biweek.start_equity, 2),
            "biweek_defending": state.biweek.defending,
            "drawdown_halted": state.drawdown_halted,
            "daily_halt_date": state.daily_halt_date,
            "restrategize_needed": state.restrategize_needed,
        },
        "equity_curve": equity,
        "benchmark_curve": bench_norm,
        "positions": state.last_positions,
        "trades": state.trades[-120:][::-1],
        "decisions": state.decisions[-120:][::-1],
        "notes": state.notes[-20:][::-1],
        "universe": config.universe,
        "benchmark": config.benchmark,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
    return out
