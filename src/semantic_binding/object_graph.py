from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

from .bindings import BindingResolver
from .facts import FactSet
from .models import Evidence, Recipe, ResolvedEdge
from .path_templates import normalize_endpoint_value, normalize_path


class ObjectGraphResolver:
    """Builds semantic entrypoint paths through arbitrary-depth object composition."""

    def __init__(self, facts: FactSet, bindings: BindingResolver, recipes: Iterable[Recipe] = ()) -> None:
        self.facts = facts
        self.bindings = bindings
        self.recipes = list(recipes)
        self.diagnostics: List[str] = []

    def resolve(self) -> List[ResolvedEdge]:
        edges: Dict[str, ResolvedEdge] = {}
        for recipe in self._recipes():
            for edge in self._resolve_recipe(recipe):
                edges[edge.id or ""] = edge
        return [edges[key] for key in sorted(edges)]

    def _recipes(self) -> List[Recipe]:
        return [r for r in self.recipes if r.type in {"object_graph", "decorator_entrypoint"}]

    def _resolve_recipe(self, recipe: Recipe) -> List[ResolvedEdge]:
        prefix_kwarg = recipe.prefix_kwarg or str(recipe.options.get("prefix_kwarg", "prefix"))
        constructor = recipe.constructor or str(recipe.options.get("constructor", ""))
        include_method = recipe.include_method or str(recipe.options.get("include_method", "include"))
        decorator_methods = set(recipe.decorator_methods or recipe.options.get("decorator_methods", []))
        path_builders = recipe.path_builder_functions or recipe.options.get("path_builder_functions", [])

        object_prefix: Dict[str, str] = {}
        object_evidence: Dict[str, Evidence] = {}
        include_parent: Dict[str, str] = {}
        include_prefix: Dict[str, str] = {}
        include_evidence: Dict[str, Evidence] = {}

        for assignment in self.facts.assignments:
            if assignment.value_kind == "construct" and (not constructor or assignment.value == constructor):
                prefix_value = assignment.kwargs.get(prefix_kwarg, "")
                prefix = normalize_endpoint_value(prefix_value, path_builders) or normalize_path(str(prefix_value or "/"))
                self._register_object(object_prefix, object_evidence, assignment.target, prefix, Evidence(
                    "object_construct",
                    f"{assignment.target} constructed as {assignment.value}",
                    assignment.file,
                    assignment.line,
                    assignment.id,
                ))

        # Add aliases after direct objects are known.
        changed = True
        while changed:
            changed = False
            for binding in self.bindings.bindings.values():
                target = binding.target
                if target in object_prefix and binding.source not in object_prefix:
                    object_prefix[binding.source] = object_prefix[target]
                    object_evidence[binding.source] = binding.evidence[0] if binding.evidence else Evidence(
                        "object_alias", f"{binding.source} aliases {target}"
                    )
                    changed = True

        for call in self.facts.calls:
            receiver = self._object_name(call.receiver, object_prefix)
            if not receiver or call.method != include_method or not call.args:
                continue
            child = self._object_name(str(call.args[0]), object_prefix)
            if not child:
                self.diagnostics.append(f"unresolved object graph include child {call.args[0]!r}")
                continue
            if child in include_parent and include_parent[child] != receiver:
                self.diagnostics.append(
                    f"ambiguous object graph parent for {child!r}: {include_parent[child]!r} vs {receiver!r}"
                )
                continue
            include_parent[child] = receiver
            prefix_value = call.kwargs.get(prefix_kwarg, "")
            if prefix_value:
                include_prefix[child] = normalize_endpoint_value(prefix_value, path_builders) or normalize_path(str(prefix_value))
            include_evidence[child] = Evidence(
                "object_include",
                f"{receiver}.{include_method} includes {child}",
                call.file,
                call.line,
                call.id,
            )

        edges: Dict[str, ResolvedEdge] = {}
        for dec in self.facts.decorators:
            receiver = self._object_name(dec.receiver, object_prefix)
            if not receiver or not dec.method:
                continue
            if decorator_methods and dec.method not in decorator_methods:
                continue
            local_path_value = dec.args[0] if dec.args else dec.kwargs.get("path", "/")
            local_path = normalize_endpoint_value(local_path_value, path_builders) or normalize_path(str(local_path_value or "/"))
            prefix, prefix_evidence = self._full_prefix(receiver, object_prefix, object_evidence, include_parent, include_prefix, include_evidence)
            path = self._join_paths(prefix, local_path)
            method = str(recipe.options.get("method_by_decorator", {}).get(dec.method, dec.method)).upper()
            evs = prefix_evidence + [Evidence("route_decorator", f"{receiver}.{dec.method} declares {local_path}", dec.file, dec.line, dec.id)]
            edge = ResolvedEdge(dec.target, path, "ROUTE", 0.95, method=method, path=path, evidence=evs)
            edges[edge.id or ""] = edge
        return [edges[key] for key in sorted(edges)]

    def _register_object(
        self,
        prefixes: Dict[str, str],
        evidence: Dict[str, Evidence],
        name: str,
        prefix: str,
        ev: Evidence,
    ) -> None:
        prefixes[name] = prefix
        evidence[name] = ev
        resolved = self.bindings.resolve_name(name)
        if resolved != name and "." in resolved:
            prefixes[resolved] = prefix
            evidence[resolved] = ev

    def _object_name(self, name: Optional[str], object_prefix: Dict[str, str]) -> Optional[str]:
        if not name:
            return None
        binding = self.bindings.bindings.get(name)
        if binding and binding.kind in {"IMPORT_ALIAS", "IMPORT_ALIAS_AMBIGUOUS", "ASSIGNMENT", "FIELD_BINDING"}:
            if binding.target in object_prefix:
                return binding.target
        if name in object_prefix:
            return name
        resolved = self.bindings.resolve_name(name)
        if resolved in object_prefix:
            return resolved
        return None

    def _full_prefix(
        self,
        name: str,
        object_prefix: Dict[str, str],
        object_evidence: Dict[str, Evidence],
        parent: Dict[str, str],
        include_prefix: Dict[str, str],
        include_evidence: Dict[str, Evidence],
    ) -> tuple[str, List[Evidence]]:
        chain: List[str] = []
        evidence: List[Evidence] = []
        current: Optional[str] = name
        seen: Set[str] = set()
        while current:
            if current in seen:
                self.diagnostics.append(f"object graph cycle detected at {current!r}")
                break
            seen.add(current)
            chain.append(object_prefix.get(current, ""))
            if current in include_prefix:
                chain.append(include_prefix[current])
            if current in object_evidence:
                evidence.append(object_evidence[current])
            if current in include_evidence:
                evidence.append(include_evidence[current])
            current = parent.get(current)
        chain.reverse()
        evidence.reverse()
        return self._join_paths(*chain), evidence

    def _join_paths(self, *parts: str) -> str:
        tokens: List[str] = []
        for part in parts:
            if not part or part == "/":
                continue
            tokens.append(str(part).strip("/"))
        if not tokens:
            return "/"
        return normalize_path("/" + "/".join(tokens))
