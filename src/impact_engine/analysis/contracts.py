"""Public contracts for the analysis orchestration layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class AnalysisOptions:
    project_path: str
    out_path: str | None = None
    support_packs: list[Any] | None = None
    support_pack_root: str = "support_packs"
    enable_remote_registry: bool = False
    create_research_requests: bool = True
    graphify_path: str | None = None
    changed_files: list[str] | None = None
    raw_graph_cache_path: str | None = None
    progress_callback: Callable[[dict[str, Any]], None] | None = None


@dataclass
class AnalysisResult:
    status: str
    path: str
    project_path: str
    graph_path: str | None
    inventory: dict[str, Any]
    languages: list[str]
    extractors_used: list[str]
    diagnostics: dict[str, Any]
    support_pack_load_errors: list[str]
    nodes: int
    edges: int
    graph: dict[str, Any]
    progress: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": self.path,
            "project_path": self.project_path,
            "graph_path": self.graph_path,
            "inventory": self.inventory,
            "languages": self.languages,
            "extractors_used": self.extractors_used,
            "diagnostics": self.diagnostics,
            "support_pack_load_errors": self.support_pack_load_errors,
            "nodes": self.nodes,
            "edges": self.edges,
            "graph": self.graph,
            "progress": self.progress,
        }
