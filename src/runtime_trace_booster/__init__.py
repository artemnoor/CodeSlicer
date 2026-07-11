"""Runtime Trace Booster.

Standalone stdlib-only runtime confirmation layer for Python call graph edges.
"""

from .graph_patch import apply_runtime_trace_to_graph
from .matcher import match_runtime_calls_to_graph
from .runner import run_runtime_trace

__all__ = [
    "apply_runtime_trace_to_graph",
    "match_runtime_calls_to_graph",
    "run_runtime_trace",
]

__version__ = "0.1.0"
