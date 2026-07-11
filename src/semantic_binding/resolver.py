from __future__ import annotations

from typing import Dict, Iterable, List

from .bindings import BindingResolver
from .dataflow import DataFlowEngine
from .endpoint_matching import match_endpoint
from .endpoint_resolver import EndpointResolver
from .facts import FactSet
from .models import Evidence, Recipe, ResolutionResult, ResolvedEdge
from .object_graph import ObjectGraphResolver
from .symbol_table import SymbolTable


class SemanticResolver:
    """Orchestrates deterministic semantic binding over facts + recipes."""

    def __init__(self, facts: FactSet, recipes: Iterable[Recipe] = ()) -> None:
        self.facts = facts
        self.recipes = list(recipes)
        self.symbol_table = SymbolTable.from_facts(facts)
        self.binding_resolver = BindingResolver(facts, self.symbol_table, self.recipes)
        self.diagnostics: List[str] = []

    def resolve(self) -> ResolutionResult:
        bindings = self.binding_resolver.resolve()
        dataflow = DataFlowEngine(self.facts, self.binding_resolver, self.recipes).build()
        edges: Dict[str, ResolvedEdge] = {}

        def add_edge(edge: ResolvedEdge) -> None:
            if not edge.evidence:
                self.diagnostics.append(f"edge {edge.kind}:{edge.source}->{edge.target} skipped: missing evidence")
                return
            edges[edge.id or ""] = edge

        for edge in self._resolve_calls():
            add_edge(edge)

        object_graph = ObjectGraphResolver(self.facts, self.binding_resolver, self.recipes)
        for edge in object_graph.resolve():
            add_edge(edge)
        self.diagnostics.extend(object_graph.diagnostics)

        endpoint_resolver = EndpointResolver(self.facts, self.binding_resolver, self.recipes)
        for edge in endpoint_resolver.resolve():
            add_edge(edge)
        self.diagnostics.extend(endpoint_resolver.diagnostics)

        for edge in self.binding_resolver.provider_resolver.edges():
            add_edge(edge)

        self._match_endpoint_edges(edges)

        diagnostics = list(self.binding_resolver.diagnostics) + self.diagnostics
        return ResolutionResult(
            symbols=self.symbol_table.symbols(),
            bindings=bindings,
            dataflow=dataflow,
            resolved_edges=sorted(edges.values(), key=lambda e: e.id or ""),
            diagnostics=diagnostics,
        )

    def _resolve_calls(self) -> List[ResolvedEdge]:
        edges: List[ResolvedEdge] = []
        for call in self.facts.calls:
            ev = Evidence("call", "resolved call" if call.function else "resolved method call", call.file, call.line, call.id)
            if call.function:
                target = self.binding_resolver.resolve_name(call.function)
                if str(target).startswith("call:"):
                    target = str(target).split(":", 1)[1]
                edges.append(ResolvedEdge(call.caller or "<module>", str(target), "CALLS", 0.9, evidence=[ev]))
                continue
            if call.receiver and call.method:
                receiver_binding = self.binding_resolver.resolve_name(call.receiver)
                receiver_type = self.binding_resolver.type_of(call.receiver)
                if receiver_type:
                    target = f"{receiver_type}.{call.method}"
                    confidence = 0.9
                else:
                    target = f"{receiver_binding}.{call.method}"
                    confidence = 0.65
                    self._diag(f"unresolved receiver type for {call.receiver}.{call.method}")
                edges.append(ResolvedEdge(call.caller or "<module>", target, "CALLS", confidence, evidence=[ev]))
        return edges

    def _match_endpoint_edges(self, edges: Dict[str, ResolvedEdge]) -> None:
        http_edges = [e for e in edges.values() if e.kind == "HTTP_CALLS"]
        route_edges = [e for e in edges.values() if e.kind in {"ROUTE", "ROUTE_HANDLES"}]
        for http_edge in http_edges:
            for route_edge in route_edges:
                if http_edge.method and route_edge.method and http_edge.method.upper() != route_edge.method.upper():
                    continue
                match = match_endpoint(http_edge.target, route_edge.target)
                if match.confidence >= 0.8:
                    method = http_edge.method if (http_edge.method and http_edge.method == route_edge.method) else None
                    ev = Evidence("endpoint_match", match.reason, fact_id=f"{http_edge.id}|{route_edge.id}")
                    edge = ResolvedEdge(
                        source=http_edge.source,
                        target=route_edge.source,
                        kind="MATCHES_ENDPOINT",
                        confidence=match.confidence,
                        method=method,
                        path=route_edge.target,
                        evidence=http_edge.evidence + route_edge.evidence + [ev],
                    )
                    edges[edge.id or ""] = edge

    def _diag(self, message: str) -> None:
        if message not in self.diagnostics:
            self.diagnostics.append(message)
