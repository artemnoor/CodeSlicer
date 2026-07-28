"""Neutral endpoint bridge facade.

Framework-specific source parsing is retained only in the explicit
compatibility adapter. Core imports this stable facade; selected framework
plugins may call adapter helpers while their migration is completed.
"""

from .support_packs.compatibility_bridge import apply_frontend_backend_endpoint_bridge

__all__ = ["apply_frontend_backend_endpoint_bridge"]
