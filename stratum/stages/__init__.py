"""Stable package surface for Stratum stage families."""

from importlib import import_module

__all__ = [
    "acquisition",
    "boilerplate",
    "cluster",
    "edit",
    "enrich",
    "normalize",
    "render",
    "search",
    "validate",
    "verify",
]


def __getattr__(name: str):
    if name == "acquisition":
        return import_module(".acquisition", __name__)
    if name == "boilerplate":
        return import_module(".boilerplate", __name__)
    if name == "cluster":
        return import_module(".cluster", __name__)
    if name == "edit":
        return import_module(".edit", __name__)
    if name == "enrich":
        return import_module(".enrich", __name__)
    if name == "normalize":
        return import_module(".normalize", __name__)
    if name == "render":
        return import_module(".render", __name__)
    if name == "search":
        return import_module(".search", __name__)
    if name == "validate":
        return import_module(".validate", __name__)
    if name == "verify":
        return import_module(".verify", __name__)
    raise AttributeError(f"module 'stratum.stages' has no attribute '{name}'")
