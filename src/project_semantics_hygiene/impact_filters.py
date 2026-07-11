from __future__ import annotations

from .models import FileRole, GraphNodeAnnotation, Reachability


class ImpactFilter:
    def filter_nodes(
        self,
        nodes: list[dict],
        node_annotations: list[GraphNodeAnnotation],
        mode: str = "main",
    ) -> list[dict]:
        mode = mode.lower()
        ann_by_id = {a.node_id: a for a in node_annotations}
        result: list[dict] = []
        for node in nodes:
            node_id = str(node.get("id", ""))
            ann = ann_by_id.get(node_id)
            reachability = ann.reachability if ann else Reachability.UNKNOWN
            if self._include(reachability, mode):
                result.append(node)
        return result

    def _include(self, reachability: Reachability, mode: str) -> bool:
        if mode == "all":
            return True
        if mode == "runtime":
            return reachability == Reachability.RUNTIME
        if mode == "tests":
            return reachability == Reachability.TEST_ONLY
        if mode == "noise":
            return reachability in {Reachability.GENERATED_ONLY, Reachability.UNREACHABLE_CANDIDATE}
        if mode == "main":
            return reachability in {Reachability.RUNTIME, Reachability.TEST_ONLY, Reachability.UNKNOWN}
        raise ValueError(f"unknown impact filter mode: {mode}")


def group_nodes_by_semantic_role(nodes: list[dict], annotations: list[GraphNodeAnnotation]) -> dict[str, list[dict]]:
    groups = {
        "routes": [],
        "services": [],
        "repositories": [],
        "tests": [],
        "frontend": [],
        "contracts": [],
        "generated": [],
        "configs": [],
        "docs": [],
        "external_libraries": [],
        "unknown": [],
    }
    ann_by_id = {a.node_id: a for a in annotations}
    for node in nodes:
        node_id = str(node.get("id", ""))
        name = str(node.get("name", "") or "")
        kind = str(node.get("kind", "") or "")
        ann = ann_by_id.get(node_id)
        file_path = (ann.file_path if ann else None) or _extract_node_file(node) or ""
        low = f"{file_path} {name} {kind} {node_id}".lower()
        role = _semantic_role(node, ann, low)
        groups[role].append(node)
    return groups


def _semantic_role(node: dict, ann: GraphNodeAnnotation | None, low: str) -> str:
    kind = str(node.get("kind", "") or "").upper()
    name = str(node.get("name", "") or "")
    node_id = str(node.get("id", "") or "")
    if ann:
        if "route" in ann.tags or kind == "ROUTE" or name.upper().startswith(("GET ", "POST ", "PUT ", "PATCH ", "DELETE ")) or node_id.upper().startswith("HTTP"):
            return "routes"
        if ann.file_role == FileRole.TEST:
            return "tests"
        if ann.file_role == FileRole.CONTRACT:
            return "contracts"
        if ann.file_role == FileRole.GENERATED or ann.reachability == Reachability.GENERATED_ONLY:
            return "generated"
        if ann.file_role == FileRole.CONFIG:
            return "configs"
        if ann.file_role == FileRole.DOCS:
            return "docs"
    if kind in {"EXTERNAL", "DEPENDENCY", "LIBRARY", "IMPORT"} or "external" in low:
        return "external_libraries"
    if "service" in low or "/services/" in low:
        return "services"
    if any(token in low for token in ["repository", "/repo", " repo", "/dao", " dao", "/store", " store"]):
        return "repositories"
    if _looks_frontend(low):
        return "frontend"
    if kind == "ROUTE" or name.upper().startswith(("GET ", "POST ", "PUT ", "PATCH ", "DELETE ")) or node_id.upper().startswith("HTTP"):
        return "routes"
    return "unknown"


def _looks_frontend(low: str) -> bool:
    return any(ext in low for ext in [".ts", ".tsx", ".js", ".jsx"]) and any(
        token in low for token in ["frontend/", "/src/components/", "/components/", "/hooks/", "/api/", "/routes/"]
    )


def _extract_node_file(node: dict) -> str | None:
    props = node.get("properties") or {}
    if isinstance(props, dict) and props.get("file"):
        return str(props["file"])
    if node.get("file"):
        return str(node["file"])
    return None
