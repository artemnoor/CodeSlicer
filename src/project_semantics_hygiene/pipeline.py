from __future__ import annotations

from collections import Counter

from .dependency_classifier import DependencyClassifier
from .file_roles import FileRoleClassifier
from .graph_annotator import GraphAnnotator
from .models import DependencyKind, FileRole, HygieneReport, ProjectFile, Reachability
from .route_normalizer import RouteNormalizer
from .rule_pack import HygieneRulePack, default_rule_pack


class HygienePipeline:
    def __init__(self, rule_pack: HygieneRulePack | None = None):
        self.rule_pack = rule_pack or default_rule_pack()
        self.file_classifier = FileRoleClassifier(self.rule_pack)
        self.dependency_classifier = DependencyClassifier(self.rule_pack)
        self.route_normalizer = RouteNormalizer()
        self.graph_annotator = GraphAnnotator()

    def run(
        self,
        files: list[ProjectFile],
        dependencies: list[tuple[str, str]] | None = None,
        declared_dependencies: dict[str, set[str]] | None = None,
        local_modules: dict[str, set[str]] | None = None,
        dev_dependencies: dict[str, set[str]] | None = None,
        graph: dict | None = None,
        routes: list[tuple[str | None, str, str | None]] | None = None,
    ) -> HygieneReport:
        diagnostics: list[str] = []
        file_classes = self.file_classifier.classify_many(files)

        deps = []
        declared_dependencies = declared_dependencies or {}
        local_modules = local_modules or {}
        dev_dependencies = dev_dependencies or {}
        for name, ecosystem in dependencies or []:
            eco = self.dependency_classifier._normalize_ecosystem(ecosystem)
            deps.append(
                self.dependency_classifier.classify_dependency(
                    name=name,
                    ecosystem=eco,
                    declared_dependencies=declared_dependencies.get(eco, set()) | declared_dependencies.get(ecosystem, set()),
                    local_modules=local_modules.get(eco, set()) | local_modules.get(ecosystem, set()),
                    dev_dependencies=dev_dependencies.get(eco, set()) | dev_dependencies.get(ecosystem, set()),
                )
            )

        canonical_routes = []
        for method, route, source in routes or []:
            canonical_routes.append(self.route_normalizer.normalize(route, method, source))

        node_annotations = []
        edge_annotations = []
        if graph is not None:
            node_annotations, edge_annotations = self.graph_annotator.annotate_graph(graph, file_classes, canonical_routes)

        summary = self._build_summary(file_classes, deps, canonical_routes, node_annotations, edge_annotations)
        if any(d.requires_research for d in deps):
            diagnostics.append("one or more dependencies require research")
        if any(f.role == FileRole.GENERATED for f in file_classes):
            diagnostics.append("generated files detected and can be filtered from runtime impact")
        if any("dead_candidate" in f.tags or "unused_candidate" in f.tags for f in file_classes):
            diagnostics.append("dead/unused candidates detected as tags, not file roles")
        if graph is None:
            diagnostics.append("graph was not provided; graph annotations are empty")

        return HygieneReport(
            files=file_classes,
            dependencies=deps,
            routes=canonical_routes,
            node_annotations=node_annotations,
            edge_annotations=edge_annotations,
            diagnostics=diagnostics,
            summary=summary,
        )

    def _build_summary(self, files, deps, routes, nodes, edges) -> dict[str, int]:
        summary: dict[str, int] = {}
        file_counts = Counter(f.role.value for f in files)
        dep_counts = Counter(d.kind.value for d in deps)
        reach_node_counts = Counter(n.reachability.value for n in nodes)
        reach_edge_counts = Counter(e.reachability.value for e in edges)
        for key, value in file_counts.items():
            summary[f"files.{key}"] = int(value)
        for key, value in dep_counts.items():
            summary[f"dependencies.{key}"] = int(value)
        for key, value in reach_node_counts.items():
            summary[f"nodes.{key}"] = int(value)
        for key, value in reach_edge_counts.items():
            summary[f"edges.{key}"] = int(value)
        summary["files.total"] = len(files)
        summary["dependencies.total"] = len(deps)
        summary["routes.total"] = len(routes)
        summary["nodes.total"] = len(nodes)
        summary["edges.total"] = len(edges)
        summary["dependencies.requires_research"] = sum(1 for d in deps if d.requires_research)
        summary["files.generated"] = sum(1 for f in files if f.is_generated)
        summary["files.tests"] = sum(1 for f in files if f.is_test)
        summary["files.contracts"] = sum(1 for f in files if f.is_contract)
        summary["files.dead_candidates"] = sum(1 for f in files if "dead_candidate" in f.tags or "unused_candidate" in f.tags)
        return summary
