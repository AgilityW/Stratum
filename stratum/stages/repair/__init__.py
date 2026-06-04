"""Repair stage package.

Repair owns post-validate briefing rewriting based on structured validate
telemetry. It keeps repair policy separate from Edit generation and Validate
judgment logic.
"""

from .repair import main

__all__ = ["main"]
