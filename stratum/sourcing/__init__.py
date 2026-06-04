"""Stable package surface for Stratum sourcing capabilities."""

from importlib import import_module

__all__ = ["discovery", "watchlist"]


def __getattr__(name: str):
    if name == "discovery":
        return import_module(".discovery", __name__)
    if name == "watchlist":
        return import_module(".watchlist", __name__)
    raise AttributeError(f"module 'stratum.sourcing' has no attribute '{name}'")
