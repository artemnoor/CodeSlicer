"""Stable compatibility interface for the selected endpoint pack."""
from __future__ import annotations

from .compatibility_loader import load_endpoint_bridge


def apply_frontend_backend_endpoint_bridge(*args, **kwargs):
    return load_endpoint_bridge().apply_frontend_backend_endpoint_bridge(*args, **kwargs)


def _legacy_apply_backend_route_source_composer(*args, **kwargs):
    return load_endpoint_bridge()._legacy_apply_backend_route_source_composer(*args, **kwargs)


def _legacy_collect_frontend_source_facts(*args, **kwargs):
    return load_endpoint_bridge()._legacy_collect_frontend_source_facts(*args, **kwargs)


__all__ = ["apply_frontend_backend_endpoint_bridge"]
