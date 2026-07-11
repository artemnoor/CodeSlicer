"""Graph model implementation. Stage 2 complete."""
import json
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Predefined schema sets from docs/GRAPH_SCHEMA.md
NODE_KINDS = {
    "PROJECT", "FILE", "MODULE", "CLASS", "FUNCTION", "METHOD",
    "PARAMETER", "ATTRIBUTE", "CALL_EXPR", "ASSIGNMENT", "ROUTE",
    "TEST", "EXTERNAL_LIBRARY", "SUPPORT_PACK"
}

EDGE_KINDS = {
    "CONTAINS", "IMPORTS", "DECLARES", "ASSIGNS", "READS", "WRITES",
    "CREATES", "INSTANCE_OF", "PARAM_BINDS_TO", "FIELD_BINDS_TO",
    "RESOLVES_TO", "CALLS", "MAY_CALL", "DEPENDS_ON", "ROUTE_HANDLES",
    "HTTP_CALLS", "MATCHES_ENDPOINT", "TESTS", "AFFECTS",
    "PROVIDED_BY_SUPPORT_PACK", "USES_COMPONENT"
}

EDGE_SOURCES = {
    "EXTRACTED", "INFERRED", "RUNTIME_CONFIRMED", "EXTERNAL_TOOL",
    "SUPPORT_PACK", "AI_PROPOSED", "MANUAL"
}

SOURCE_PRIORITY = {
    "RUNTIME_CONFIRMED": 60,
    "INFERRED": 50,
    "SUPPORT_PACK": 40,
    "EXTRACTED": 30,
    "EXTERNAL_TOOL": 20,
    "MANUAL": 10,
    "AI_PROPOSED": 5,
}


def _evidence_key(ev: "Evidence") -> Tuple[Any, ...]:
    return (ev.description, ev.file, ev.line, ev.source)


@dataclass
class Evidence:
    description: str
    file: Optional[str] = None
    line: Optional[int] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res = {"description": self.description}
        if self.file is not None:
            res["file"] = self.file
        if self.line is not None:
            res["line"] = self.line
        if self.source is not None:
            res["source"] = self.source
        return res


@dataclass
class Node:
    id: str
    kind: str
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = str(self.id)
        self.kind = str(self.kind)
        self.name = str(self.name)
        if self.kind not in NODE_KINDS:
            raise ValueError(f"Invalid Node kind: {self.kind}. Must be one of {NODE_KINDS}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "properties": self.properties,
        }


@dataclass
class Edge:
    id: str
    kind: str
    from_node: str
    to_node: str
    source: str = "EXTRACTED"
    confidence: float = 1.0
    evidence: List[Evidence] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = str(self.id)
        self.kind = str(self.kind)
        self.from_node = str(self.from_node)
        self.to_node = str(self.to_node)
        self.source = str(self.source)
        self.confidence = float(self.confidence)
        if self.kind not in EDGE_KINDS:
            raise ValueError(f"Invalid Edge kind: {self.kind}. Must be one of {EDGE_KINDS}")
        if self.source not in EDGE_SOURCES:
            raise ValueError(f"Invalid Edge source (provenance): {self.source}. Must be one of {EDGE_SOURCES}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Invalid Edge confidence: {self.confidence}. Must be between 0.0 and 1.0 inclusive")

    @property
    def rule_id(self) -> str:
        return str(self.properties.get("support_pack_rule_id") or self.properties.get("rule_id") or "")

    def semantic_key(self, include_source: bool = True) -> Tuple[str, str, str, str, str] | Tuple[str, str, str, str]:
        base = (self.from_node, self.to_node, self.kind, self.rule_id)
        if include_source:
            return (*base, self.source)
        return base

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "from": self.from_node,
            "to": self.to_node,
            "source": self.source,
            "confidence": self.confidence,
            "evidence": [ev.to_dict() for ev in self.evidence],
            "properties": self.properties,
        }


@dataclass
class GraphDocument:
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Runtime-only indexes. They are intentionally excluded from serialization.
    _node_index: Dict[str, Node] = field(default_factory=dict, init=False, repr=False)
    _edge_index: Dict[Tuple[str, str, str, str], Edge] = field(default_factory=dict, init=False, repr=False)
    _edge_base_index: Dict[Tuple[str, str, str, str], Edge] = field(default_factory=dict, init=False, repr=False)
    _edge_id_index: Dict[str, Edge] = field(default_factory=dict, init=False, repr=False)
    _incoming_index: Dict[str, List[Edge]] = field(default_factory=dict, init=False, repr=False)
    _outgoing_index: Dict[str, List[Edge]] = field(default_factory=dict, init=False, repr=False)

    def _ensure_indexes(self) -> None:
        """Rebuild indexes if callers constructed a document with raw lists."""
        if len(self._node_index) != len(self.nodes) or len(self._edge_id_index) != len(self.edges):
            self._node_index = {node.id: node for node in self.nodes}
            self._edge_index = {}
            self._edge_base_index = {}
            self._edge_id_index = {}
            self._incoming_index = {}
            self._outgoing_index = {}
            for edge in self.edges:
                self._edge_index[edge.semantic_key(True)] = edge
                self._edge_base_index[edge.semantic_key(False)] = edge
                self._edge_id_index[edge.id] = edge
                self._incoming_index.setdefault(edge.to_node, []).append(edge)
                self._outgoing_index.setdefault(edge.from_node, []).append(edge)

    def add_node(self, node: Node) -> None:
        self._ensure_indexes()
        existing = self._node_index.get(node.id)
        if existing is None:
            self.nodes.append(node)
            self._node_index[node.id] = node
            return
        # Keep stable id/kind/name; merge properties without duplicate list spam.
        if existing.kind != node.kind:
            existing.properties.setdefault("kind_conflicts", [])
            conflict = {"existing": existing.kind, "incoming": node.kind}
            if conflict not in existing.properties["kind_conflicts"]:
                existing.properties["kind_conflicts"].append(conflict)
        if not existing.name and node.name:
            existing.name = node.name
        for k, v in node.properties.items():
            if k not in existing.properties:
                existing.properties[k] = v
            elif isinstance(existing.properties[k], list) and isinstance(v, list):
                for item in v:
                    if item not in existing.properties[k]:
                        existing.properties[k].append(item)
            elif existing.properties[k] != v:
                # Preserve the first stable value and record conflict for diagnostics.
                conflicts = existing.properties.setdefault("property_conflicts", {})
                vals = conflicts.setdefault(k, [])
                if v not in vals:
                    vals.append(v)

    def _merge_edge(self, existing: Edge, incoming: Edge) -> None:
        if SOURCE_PRIORITY.get(incoming.source, 0) > SOURCE_PRIORITY.get(existing.source, 0):
            existing.source = incoming.source
        existing.confidence = max(existing.confidence, incoming.confidence)
        existing.properties.update(incoming.properties)
        observations = existing.properties.setdefault("observations", [])
        for observation in incoming.properties.get("observations", []) or []:
            if observation not in observations:
                observations.append(observation)
        seen = {_evidence_key(ev) for ev in existing.evidence}
        for ev in incoming.evidence:
            key = _evidence_key(ev)
            if key not in seen:
                existing.evidence.append(ev)
                seen.add(key)

    def _dedupe_edge_evidence(self, edge: Edge) -> None:
        seen = set()
        unique = []
        for ev in edge.evidence:
            key = _evidence_key(ev)
            if key not in seen:
                unique.append(ev)
                seen.add(key)
        edge.evidence = unique

    def add_edge(self, edge: Edge) -> None:
        if not edge.from_node.strip() or not edge.to_node.strip():
            self.metadata.setdefault("invalid_edges", []).append({
                "edge_id": edge.id,
                "reason": "missing_endpoint",
                "from": edge.from_node,
                "to": edge.to_node,
            })
            return
        self._ensure_indexes()
        self._dedupe_edge_evidence(edge)
        # Exact semantic dedupe required by acceptance: from/to/kind/source/rule_id.
        exact = self._edge_index.get(edge.semantic_key(True))
        if exact is not None:
            self._merge_edge(exact, edge)
            return
        # Conflict resolution: same semantic edge and rule id, different source -> keep higher-priority provenance.
        conflict = self._edge_base_index.get(edge.semantic_key(False))
        if conflict is not None:
            self._merge_edge(conflict, edge)
            self._rebuild_edge_indexes()
            return
        # Id dedupe fallback.
        same_id = self._edge_id_index.get(edge.id)
        if same_id is not None:
            self._merge_edge(same_id, edge)
            self._rebuild_edge_indexes()
            return
        self.edges.append(edge)
        self._edge_index[edge.semantic_key(True)] = edge
        self._edge_base_index[edge.semantic_key(False)] = edge
        self._edge_id_index[edge.id] = edge
        self._incoming_index.setdefault(edge.to_node, []).append(edge)
        self._outgoing_index.setdefault(edge.from_node, []).append(edge)

    def _rebuild_edge_indexes(self) -> None:
        self._edge_index = {edge.semantic_key(True): edge for edge in self.edges}
        self._edge_base_index = {edge.semantic_key(False): edge for edge in self.edges}
        self._edge_id_index = {edge.id: edge for edge in self.edges}
        self._incoming_index = {}
        self._outgoing_index = {}
        for edge in self.edges:
            self._incoming_index.setdefault(edge.to_node, []).append(edge)
            self._outgoing_index.setdefault(edge.from_node, []).append(edge)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in sorted(self.nodes, key=lambda n: n.id)],
            "edges": [e.to_dict() for e in sorted(self.edges, key=lambda e: (e.from_node, e.to_node, e.kind, e.source, e.rule_id, e.id))],
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphDocument":
        graph = cls(metadata=data.get("metadata", {}))
        for n in data.get("nodes", []):
            graph.add_node(Node(
                id=n["id"],
                kind=n["kind"],
                name=n.get("name") or n["id"],
                properties=n.get("properties", {})
            ))
        for e in data.get("edges", []):
            evidences = []
            for ev in e.get("evidence", []):
                evidences.append(Evidence(
                    description=ev.get("description", ""),
                    file=ev.get("file"),
                    line=ev.get("line"),
                    source=ev.get("source")
                ))
            from_n = e.get("from") or e.get("from_node")
            to_n = e.get("to") or e.get("to_node")
            if not from_n or not to_n:
                graph.metadata.setdefault("invalid_edges", []).append({
                    "edge_id": e.get("id"),
                    "reason": "missing_endpoint",
                    "from": from_n or "",
                    "to": to_n or "",
                })
                continue
            graph.add_edge(Edge(
                id=e.get("id") or f"{from_n}__{e.get('kind')}__{to_n}",
                kind=e["kind"],
                from_node=from_n,
                to_node=to_n,
                source=e.get("source", "EXTRACTED"),
                confidence=e.get("confidence", 1.0),
                evidence=evidences,
                properties=e.get("properties", {})
            ))
        return graph

    @classmethod
    def from_json(cls, json_str: str) -> "GraphDocument":
        return cls.from_dict(json.loads(json_str))


@dataclass
class FactDocument:
    """Raw extractor facts kept conceptually separate from resolved edges."""

    declarations: list[dict[str, Any]] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    callsites: list[dict[str, Any]] = field(default_factory=list)
    assignments: list[dict[str, Any]] = field(default_factory=list)
    decorators: list[dict[str, Any]] = field(default_factory=list)
    locations: list[dict[str, Any]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_graph(cls, graph: GraphDocument) -> "FactDocument":
        facts = cls()
        def stable_fact(kind: str, subject: str, target: str | None, properties: dict[str, Any], file: str | None, line: int | None) -> dict[str, Any]:
            normalized = {str(k): v for k, v in properties.items() if k not in {"line", "absolute_path", "timestamp"}}
            identity = json.dumps({"kind": kind, "subject": subject, "target": target, "properties": normalized, "file": str(file or "").replace("\\", "/")}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            return {"fact_id": "fact:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20], "fact_kind": kind, "language": _fact_language(str(file or "")), "file": file, "scope": properties.get("scope"), "canonical_subject": subject, "canonical_target": target, "normalized_properties": normalized, "evidence_line": line}
        for node in graph.nodes:
            item = node.to_dict()
            facts.facts.append(stable_fact(node.kind, node.id, None, node.properties, node.properties.get("file") or node.properties.get("path"), node.properties.get("line")))
            facts.locations.append({"id": node.id, "file": node.properties.get("file"), "line": node.properties.get("line")})
            if node.kind in {"CLASS", "FUNCTION", "METHOD", "MODULE", "FILE"}:
                facts.declarations.append(item)
            elif node.kind == "CALL_EXPR":
                facts.callsites.append(item)
            elif node.kind == "ASSIGNMENT":
                facts.assignments.append(item)
            for decorator in node.properties.get("decorators", []) or []:
                facts.decorators.append({"target": node.id, "decorator": decorator, "file": node.properties.get("file"), "line": node.properties.get("line")})
        for edge in graph.edges:
            evidence = edge.evidence[0] if edge.evidence else None
            facts.facts.append(stable_fact(edge.kind, edge.from_node, edge.to_node, edge.properties, getattr(evidence, "file", None), getattr(evidence, "line", None)))
            if edge.kind == "IMPORTS":
                facts.imports.append(edge.to_dict())
        return facts

    def summary(self) -> dict[str, int]:
        return {key: len(value) for key, value in {
            "declarations": self.declarations,
            "imports": self.imports,
            "callsites": self.callsites,
            "assignments": self.assignments,
            "decorators": self.decorators,
            "locations": self.locations,
        }.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "impact-engine.fact-document.v1",
            "declarations": sorted(self.declarations, key=lambda item: str(item.get("id", ""))),
            "imports": sorted(self.imports, key=lambda item: str(item.get("id", ""))),
            "callsites": sorted(self.callsites, key=lambda item: str(item.get("id", ""))),
            "assignments": sorted(self.assignments, key=lambda item: str(item.get("id", ""))),
            "decorators": sorted(self.decorators, key=lambda item: (str(item.get("target", "")), str(item.get("decorator", "")))),
            "locations": sorted(self.locations, key=lambda item: str(item.get("id", ""))),
            "facts": sorted(self.facts, key=lambda item: str(item.get("fact_id", ""))),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FactDocument":
        return cls(
            declarations=list(data.get("declarations", [])),
            imports=list(data.get("imports", [])),
            callsites=list(data.get("callsites", [])),
            assignments=list(data.get("assignments", [])),
            decorators=list(data.get("decorators", [])),
            locations=list(data.get("locations", [])),
            facts=list(data.get("facts", [])),
        )


def _fact_language(file_path: str) -> str:
    suffix = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return {"py": "python", "js": "javascript", "jsx": "javascript", "ts": "typescript", "tsx": "typescript", "go": "go", "java": "java"}.get(suffix, "unknown")


@dataclass
class FactDiff:
    changed_files: list[str] = field(default_factory=list)
    added_fact_ids: list[str] = field(default_factory=list)
    removed_fact_ids: list[str] = field(default_factory=list)
    modified_fact_ids: list[str] = field(default_factory=list)
    unchanged_fact_ids: list[str] = field(default_factory=list)
    changed_dependency_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"changed_files": sorted(self.changed_files), "added_fact_ids": sorted(self.added_fact_ids), "removed_fact_ids": sorted(self.removed_fact_ids), "modified_fact_ids": sorted(self.modified_fact_ids), "unchanged_fact_ids": sorted(self.unchanged_fact_ids), "changed_dependency_keys": sorted(self.changed_dependency_keys)}


def diff_fact_documents(old: FactDocument, new: FactDocument, changed_files: list[str]) -> FactDiff:
    old_map = {fact.get("fact_id"): fact for fact in old.facts if fact.get("fact_id")}
    new_map = {fact.get("fact_id"): fact for fact in new.facts if fact.get("fact_id")}
    old_ids, new_ids = set(old_map), set(new_map)
    modified = []
    for fact_id in old_ids & new_ids:
        if old_map[fact_id].get("normalized_properties") != new_map[fact_id].get("normalized_properties"):
            modified.append(fact_id)
    changed = set(old_ids ^ new_ids) | set(modified)
    keys = set()
    for fact in list(old_map.values()) + list(new_map.values()):
        if fact.get("fact_id") in changed:
            keys.add(f"file:{fact.get('file')}")
            if fact.get("canonical_subject"): keys.add(f"symbol:{fact['canonical_subject']}")
            if fact.get("canonical_target"): keys.add(f"symbol:{fact['canonical_target']}")
    return FactDiff(list(changed_files), list(new_ids - old_ids), list(old_ids - new_ids), modified, list(old_ids & new_ids - set(modified)), sorted(keys))
