"""``app.api.v1`` package — re-exports the v1 router.

Re-exporting ``router`` here lets callers do::

    from app.api.v1 import router

instead of reaching into ``app.api.v1.router`` directly. The re-export is
intentional: it gives impact-analysis tools an extra import edge to
follow.
"""
from app.api.v1.router import router

__all__ = ["router"]
