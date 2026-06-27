"""Broker abstraction: one interface, an Alpaca REST adapter, and an offline
simulator used by the backtester and the test suite."""
from .base import Account, Broker, Position  # noqa: F401


def make_broker(config, secrets):
    """Factory: build the broker named in config (falls back to sim if no keys)."""
    name = config.broker
    if name == "alpaca":
        from .alpaca import AlpacaBroker
        if not secrets.has_alpaca:
            raise RuntimeError(
                "broker=alpaca but no ALPACA_API_KEY/SECRET found. "
                "Copy .env.example to .env and fill in your paper keys, or set "
                "broker: sim in config.yaml for an offline dry run."
            )
        return AlpacaBroker(secrets)
    if name == "sim":
        from .sim import SimBroker
        return SimBroker()
    raise ValueError(f"Unknown broker: {name}")
