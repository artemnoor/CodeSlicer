"""Polling watch wrapper around the safe incremental contract."""
from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any, Callable

from impact_engine.incremental import incremental_update, save_snapshot
from impact_engine.analysis_lock import analysis_lock


def watch_project(
    project_path: str,
    analyzer: Callable[[], dict[str, Any]],
    previous_snapshot: dict[str, Any] | None = None,
    interval_seconds: float = 1.0,
    iterations: int | None = None,
    out_path: str | None = None,
    snapshot_path: str | None = None,
    previous_graph_path: str | None = None,
) -> Iterator[dict[str, Any]]:
    snapshot = previous_snapshot
    count = 0
    while iterations is None or count < iterations:
        with analysis_lock(project_path, owner="watch"):
            result = incremental_update(
                project_path,
                analyzer,
                snapshot,
                out_path,
                previous_graph_path=previous_graph_path,
            )
            if snapshot_path:
                save_snapshot(result["incremental"]["snapshot"], snapshot_path)
        snapshot = result["incremental"]["snapshot"]
        yield result
        count += 1
        if iterations is None or count < iterations:
            time.sleep(max(0.05, interval_seconds))
