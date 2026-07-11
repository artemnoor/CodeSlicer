from __future__ import annotations

from .models import CanonicalRoute, FileClassification, FileRole, GraphEdgeAnnotation, GraphNodeAnnotation, Reachability


class GraphAnnotator:
    def annotate_graph(
        self,
        graph: dict,
        file_classifications: list[FileClassification],
        routes: list[CanonicalRoute] | None = None,
    ) -> tuple[list[GraphNodeAnnotation], list[GraphEdgeAnnotation]]:
        class_by_path = {self._norm(fc.path): fc for fc in file_classifications}
        node_annotations: list[GraphNodeAnnotation] = []
        ann_by_id: dict[str, GraphNodeAnnotation] = {}

        for node in graph.get("nodes", []) or []:
            ann = self._annotate_node(node, class_by_path)
            node_annotations.append(ann)
            ann_by_id[ann.node_id] = ann

        edge_annotations: list[GraphEdgeAnnotation] = []
        for idx, edge in enumerate(graph.get("edges", []) or []):
            ann = self._annotate_edge(edge, ann_by_id, idx)
            edge_annotations.append(ann)

        return node_annotations, edge_annotations

    def _annotate_node(self, node: dict, class_by_path: dict[str, FileClassification]) -> GraphNodeAnnotation:
        node_id = str(node.get("id", ""))
        kind = str(node.get("kind", "") or "")
        name = str(node.get("name", "") or "")
        file_path = self._extract_file_path(node)
        fc = class_by_path.get(self._norm(file_path)) if file_path else None
        tags: list[str] = []
        reasons: list[str] = []
        reachability = Reachability.UNKNOWN
        confidence = 0.35

        if kind.upper() == "ROUTE" or kind.upper().endswith("ROUTE") or name.upper().startswith(("GET ", "POST ", "PUT ", "PATCH ", "DELETE ")) or node_id.upper().startswith(("HTTP", "GET ", "POST ")):
            tags.append("route")
            reasons.append("node kind/name/id indicates route")

        if fc is None:
            reasons.append("no file classification available for node")
        else:
            tags.extend(fc.tags)
            if fc.role == FileRole.TEST:
                reachability = Reachability.TEST_ONLY
                tags.append("test")
                confidence = 0.90
                reasons.append("node belongs to test file")
            elif fc.role == FileRole.GENERATED:
                reachability = Reachability.GENERATED_ONLY
                tags.append("generated")
                confidence = 0.92
                reasons.append("node belongs to generated file")
            elif fc.role == FileRole.CONTRACT:
                reachability = Reachability.RUNTIME
                tags.append("contract")
                confidence = 0.82
                reasons.append("node belongs to contract/schema file")
            elif any(t in fc.tags for t in ["dead_candidate", "unused_candidate"]):
                reachability = Reachability.UNREACHABLE_CANDIDATE
                confidence = 0.76
                reasons.append("source file has dead/unused candidate tag")
            elif fc.role == FileRole.SOURCE:
                reachability = Reachability.RUNTIME
                confidence = 0.86
                reasons.append("node belongs to runtime source file")
            elif fc.role in {FileRole.CONFIG, FileRole.DOCS, FileRole.FIXTURE, FileRole.MIGRATION, FileRole.VENDOR, FileRole.BUILD_ARTIFACT}:
                reachability = Reachability.UNKNOWN
                tags.append(fc.role.value.lower())
                confidence = 0.72
                reasons.append(f"node belongs to {fc.role.value.lower()} file")

            if fc.role == FileRole.CONTRACT and "contract" not in tags:
                tags.append("contract")

        return GraphNodeAnnotation(
            node_id=node_id,
            file_path=file_path,
            file_role=fc.role if fc else None,
            reachability=reachability,
            tags=sorted(set(tags)),
            confidence=confidence,
            reasons=reasons,
        )

    def _annotate_edge(self, edge: dict, ann_by_id: dict[str, GraphNodeAnnotation], idx: int) -> GraphEdgeAnnotation:
        edge_id = str(edge.get("id") or f"edge:{idx}")
        kind = str(edge.get("kind", "") or "")
        from_id = str(edge.get("from", "") or "")
        to_id = str(edge.get("to", "") or "")
        left = ann_by_id.get(from_id)
        right = ann_by_id.get(to_id)
        anns = [a for a in [left, right] if a is not None]
        tags: list[str] = []
        reasons: list[str] = []

        if any(a.reachability == Reachability.GENERATED_ONLY for a in anns):
            reachability = Reachability.GENERATED_ONLY
            noise = 0.90
            tags.append("generated")
            reasons.append("edge touches generated node")
            confidence = 0.88
        elif kind.upper() == "TESTS" or (anns and all(a.reachability == Reachability.TEST_ONLY for a in anns)):
            reachability = Reachability.TEST_ONLY
            noise = 0.40
            tags.append("test")
            reasons.append("edge is test-only or explicit TESTS edge")
            confidence = 0.86
        elif any(a.reachability == Reachability.UNREACHABLE_CANDIDATE or any(t in a.tags for t in ["dead_candidate", "unused_candidate"]) for a in anns):
            reachability = Reachability.UNREACHABLE_CANDIDATE
            noise = 0.70
            tags.append("dead_candidate")
            reasons.append("edge touches dead/unused candidate node")
            confidence = 0.76
        else:
            reachability = Reachability.RUNTIME
            noise = 0.10
            reasons.append("no generated/test/dead signal on edge endpoints")
            confidence = 0.75 if anns else 0.45

        return GraphEdgeAnnotation(
            edge_id=edge_id,
            reachability=reachability,
            noise_score=noise,
            tags=sorted(set(tags)),
            confidence=confidence,
            reasons=reasons,
        )

    def _extract_file_path(self, node: dict) -> str | None:
        props = node.get("properties") or {}
        if isinstance(props, dict) and props.get("file"):
            return str(props["file"])
        if node.get("file"):
            return str(node["file"])
        node_id = str(node.get("id", "") or "")
        if node_id.startswith("file:"):
            return node_id.removeprefix("file:")
        if "::" in node_id:
            prefix = node_id.split("::", 1)[0]
            if "/" in prefix or "." in prefix:
                return prefix
        return None

    def _norm(self, path: str | None) -> str:
        if not path:
            return ""
        return path.replace("\\", "/").lstrip("./")
