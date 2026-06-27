"""Configuration loading.

Loads ``config.yaml`` (behaviour) and environment variables (secrets).
Secrets NEVER live in the repo — only in a local ``.env`` (gitignored) or in
GitHub Actions Secrets.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:  # optional; only needed for local .env loading
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


@dataclass
class Secrets:
    """Broker / API credentials, read from the environment."""

    alpaca_key: str = ""
    alpaca_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    anthropic_key: str = ""
    discord_webhook: str = ""
    telegram_token: str = ""
    telegram_chat: str = ""

    @property
    def has_alpaca(self) -> bool:
        return bool(self.alpaca_key and self.alpaca_secret)

    @classmethod
    def from_env(cls) -> "Secrets":
        load_dotenv(ROOT / ".env")
        return cls(
            alpaca_key=os.getenv("ALPACA_API_KEY", "").strip(),
            alpaca_secret=os.getenv("ALPACA_API_SECRET", "").strip(),
            alpaca_base_url=os.getenv(
                "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
            ).strip(),
            anthropic_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            discord_webhook=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        )


@dataclass
class Config:
    """Parsed view of ``config.yaml`` with convenient accessors."""

    raw: dict[str, Any] = field(default_factory=dict)

    # --- top level ---
    @property
    def mode(self) -> str:
        return self.raw.get("mode", "paper")

    @property
    def broker(self) -> str:
        return self.raw.get("broker", "alpaca")

    @property
    def account_label(self) -> str:
        return self.raw.get("account_label", "Zimupaper")

    @property
    def universe(self) -> list[str]:
        return list(self.raw.get("universe", []))

    @property
    def benchmark(self) -> str:
        return self.raw.get("benchmark", "SPY")

    @property
    def cash_asset(self) -> str:
        return self.raw.get("cash_asset", "BIL")

    # --- nested sections (return plain dicts) ---
    @property
    def targets(self) -> dict[str, Any]:
        return self.raw.get("targets", {})

    @property
    def risk(self) -> dict[str, Any]:
        return self.raw.get("risk", {})

    @property
    def agent(self) -> dict[str, Any]:
        return self.raw.get("agent", {})

    @property
    def strategies(self) -> dict[str, Any]:
        return self.raw.get("strategies", {})

    @property
    def data(self) -> dict[str, Any]:
        return self.raw.get("data", {})

    @property
    def weekly_gain(self) -> float:
        return float(self.targets.get("weekly_gain", 0.01))

    @property
    def all_symbols(self) -> list[str]:
        """Universe + benchmark + cash asset, de-duplicated, order-preserved."""
        seen: dict[str, None] = {}
        for s in [*self.universe, self.benchmark, self.cash_asset]:
            if s:
                seen.setdefault(s, None)
        return list(seen.keys())

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(p, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls(raw=raw)
