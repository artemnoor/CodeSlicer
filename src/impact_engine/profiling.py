"""Low-overhead, local-only profiling for analysis pipeline runs."""
from __future__ import annotations

from contextlib import contextmanager
import time
from typing import Any, Iterator


PROFILE_STAGES = (
    "inventory",
    "cache_lookup",
    "snapshot_hashing",
    "plugin_selection",
    "extraction",
    "normalization",
    "semantic_binding",
    "framework_hooks",
    "precision_resolution",
    "frontend_backend_projection",
    "graph_quality",
    "review_projection",
    "serialization",
)

WORK_COUNTERS = (
    "files_seen",
    "files_reused",
    "files_reparsed",
    "facts_reused",
    "facts_rebuilt",
    "edges_reused",
    "edges_rebuilt",
)


class AnalysisProfiler:
    """Accumulates monotonic stage timings and non-content work counters."""

    def __init__(self) -> None:
        self.timings = {stage: 0.0 for stage in PROFILE_STAGES}
        self.work: dict[str, Any] = {counter: 0 for counter in WORK_COUNTERS}
        self.work["plugins_executed"] = []
        self.work["plugins_skipped"] = []

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.timings[stage] = self.timings.get(stage, 0.0) + (time.perf_counter() - started)

    def add_work(self, **values: Any) -> None:
        for key, value in values.items():
            if key in {"plugins_executed", "plugins_skipped"}:
                current = self.work.setdefault(key, [])
                for item in value or []:
                    if item not in current:
                        current.append(item)
            elif key in WORK_COUNTERS:
                self.work[key] = int(self.work.get(key, 0)) + int(value or 0)

    def snapshot(self) -> dict[str, Any]:
        return {
            "stage_timings_seconds": {
                stage: round(float(self.timings.get(stage, 0.0)), 6)
                for stage in PROFILE_STAGES
            },
            "work": {
                **{counter: int(self.work.get(counter, 0)) for counter in WORK_COUNTERS},
                "plugins_executed": sorted(set(self.work.get("plugins_executed", []))),
                "plugins_skipped": sorted(set(self.work.get("plugins_skipped", []))),
            },
        }
