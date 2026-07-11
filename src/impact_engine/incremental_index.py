"""Language-neutral reverse dependency index for incremental invalidation."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass(frozen=True)
class DependencyRecord:
    source_id: str
    dependent_id: str
    dependency_kind: str
    evidence_file: str | None = None
    evidence_line: int | None = None
    resolver: str | None = None
    support_pack: str | None = None
    confidence: float | None = None
    def to_dict(self) -> dict[str, Any]: return asdict(self)

class ReverseDependencyIndex:
    def __init__(self) -> None:
        self.by_source: dict[str, list[DependencyRecord]] = {}
        self.by_dependent: dict[str, list[DependencyRecord]] = {}
    def add(self, record: DependencyRecord) -> None:
        self.by_source.setdefault(record.source_id, []).append(record)
        self.by_dependent.setdefault(record.dependent_id, []).append(record)
    def to_dict(self) -> dict[str, Any]:
        records = [r.to_dict() for values in self.by_source.values() for r in values]
        return {"record_count": len(records), "source_count": len(self.by_source), "dependent_count": len(self.by_dependent), "records": sorted(records, key=lambda r: (r["source_id"], r["dependent_id"], r["dependency_kind"]))}

def build_reverse_dependency_index(graph) -> ReverseDependencyIndex:
    index = ReverseDependencyIndex()
    for edge in graph.edges:
        evidence = edge.evidence[0] if edge.evidence else None
        pack = edge.properties.get("support_pack")
        if isinstance(pack, dict): pack = pack.get("support_pack")
        index.add(DependencyRecord(edge.to_node, edge.from_node, edge.kind, getattr(evidence, "file", None), getattr(evidence, "line", None), edge.properties.get("resolver_hook_name") or edge.properties.get("extractor_id"), pack or edge.properties.get("support_pack_library"), edge.confidence))
    return index

def affected_closure(graph, fact_diff: dict, fact_documents=None) -> dict[str, Any]:
    """Compute a bounded deterministic closure from changed facts/keys."""
    from impact_engine.resolver_registry import select_resolvers
    invalid_fact_ids = set(fact_diff.get("removed_fact_ids", [])) | set(fact_diff.get("modified_fact_ids", []))
    keys = set(fact_diff.get("changed_dependency_keys", []))
    affected_edges = []
    affected_nodes = set()
    for edge in graph.edges:
        props = edge.properties or {}
        edge_facts = set(props.get("source_fact_ids", []))
        edge_keys = set(props.get("dependency_keys", []))
        if edge_facts.intersection(invalid_fact_ids) or edge_keys.intersection(keys):
            affected_edges.append(edge.id)
            affected_nodes.update((edge.from_node, edge.to_node))
    fact_kinds = []
    if fact_documents:
        facts = fact_documents[1].facts if len(fact_documents) > 1 else []
        fact_kinds = [str(f.get("fact_kind")) for f in facts if f.get("fact_id") in invalid_fact_ids or f.get("fact_id") in set(fact_diff.get("added_fact_ids", []))]
    rerun, skipped = select_resolvers(fact_kinds, keys)
    return {"affected_fact_ids": sorted(invalid_fact_ids | set(fact_diff.get("added_fact_ids", []))), "affected_dependency_keys": sorted(keys), "affected_edge_ids": sorted(affected_edges), "affected_resolver_ids": rerun, "skipped_resolver_ids": skipped, "affected_node_ids": sorted(affected_nodes)}
