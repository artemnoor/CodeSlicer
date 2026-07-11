"""Frontend/backend endpoint resolver.

The public API is intentionally small:

    resolve_frontend_backend_endpoints(input_data: dict) -> dict

The package works on already-extracted facts. It does not parse source files.
"""

from .canonicalize import canonicalize_path, canonicalize_route
from .evaluator import PathEvaluator
from .resolver import resolve_frontend_backend_endpoints

__all__ = [
    "PathEvaluator",
    "canonicalize_path",
    "canonicalize_route",
    "resolve_frontend_backend_endpoints",
]

__version__ = "0.1.0"
