"""Thin manifest-facing entrypoint; all logic remains in impact_engine.adapters."""
from impact_engine.adapters.graphify import build_graphify_overlay

__all__ = ["build_graphify_overlay"]
