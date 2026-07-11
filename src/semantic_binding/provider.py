from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from .facts import FactSet
from .models import AssignmentFact, Binding, Evidence, Recipe, ResolvedEdge


@dataclass
class ProviderRecord:
    provider: str
    provides: str
    dependencies: List[str] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)


class ProviderResolver:
    """Generic provider/factory binding over normalized assignment/call facts."""

    def __init__(self, facts: FactSet, recipes: Iterable[Recipe] = ()) -> None:
        self.facts = facts
        self.recipes = list(recipes)
        self.records: Dict[str, ProviderRecord] = {}
        self.diagnostics: List[str] = []
        self._indexed = False

    def index(self) -> Dict[str, ProviderRecord]:
        if self._indexed:
            return self.records
        for assignment in self.facts.assignments:
            record = self._record_from_assignment(assignment)
            if not record:
                continue
            existing = self.records.get(record.provider)
            if existing and existing.provides != record.provides:
                self.diagnostics.append(
                    f"ambiguous provider {record.provider!r}: {existing.provides!r} vs {record.provides!r}"
                )
                continue
            self.records[record.provider] = record
        self._indexed = True
        return self.records

    def binding_for_factory(self, assignment: AssignmentFact) -> Optional[Binding]:
        record = self.index().get(assignment.target)
        if not record:
            return None
        return Binding(record.provider, record.provides, "PROVIDER_FACTORY", 0.94, list(record.evidence))

    def target_for_provider_call(self, provider_name: str) -> Optional[str]:
        self.index()
        if provider_name in self.records:
            return self.records[provider_name].provides
        for recipe in self.recipes:
            if recipe.type == "constructor_provider" and provider_name in recipe.providers:
                return recipe.providers[provider_name]
        return None

    def edges(self) -> List[ResolvedEdge]:
        self.index()
        edges: Dict[str, ResolvedEdge] = {}
        for record in self.records.values():
            for dep in record.dependencies:
                edge = ResolvedEdge(
                    source=record.provides,
                    target=dep,
                    kind="DEPENDS_ON",
                    confidence=0.9,
                    evidence=list(record.evidence),
                )
                edges[edge.id or ""] = edge
        return [edges[key] for key in sorted(edges)]

    def _record_from_assignment(self, assignment: AssignmentFact) -> Optional[ProviderRecord]:
        factory_names = self._factory_names()
        is_factory = assignment.value_kind in {"provider_factory", "factory"}
        if assignment.value_kind == "call" and str(assignment.value) in factory_names:
            is_factory = True
        if not is_factory:
            return None

        provides = self._provided_symbol(assignment, factory_names)
        if not provides:
            self.diagnostics.append(f"provider factory {assignment.target!r} has no provided symbol")
            return None

        deps = self._dependency_symbols(assignment)
        ev = Evidence(
            "provider_factory",
            f"{assignment.target} provides {provides}" + (f" with dependencies {deps}" if deps else ""),
            assignment.file,
            assignment.line,
            assignment.id,
        )
        return ProviderRecord(assignment.target, provides, deps, [ev])

    def _factory_names(self) -> Set[str]:
        names: Set[str] = set()
        for recipe in self.recipes:
            if recipe.type != "provider_factory":
                continue
            if recipe.constructor:
                names.add(recipe.constructor)
            for name in recipe.options.get("factory_functions", []):
                names.add(str(name))
        return names

    def _provided_symbol(self, assignment: AssignmentFact, factory_names: Set[str]) -> Optional[str]:
        if assignment.type_name:
            return assignment.type_name
        explicit = assignment.kwargs.get("provides") or assignment.kwargs.get("provided")
        if explicit:
            return str(explicit)
        if assignment.args:
            return str(assignment.args[0])
        if assignment.value_kind == "provider_factory" and assignment.value and str(assignment.value) not in factory_names:
            return str(assignment.value)
        return None

    def _dependency_symbols(self, assignment: AssignmentFact) -> List[str]:
        ignored = {"provides", "provided", "scope", "singleton", "name"}
        deps: List[str] = []
        for key, value in sorted(assignment.kwargs.items()):
            if key in ignored:
                continue
            if isinstance(value, str):
                deps.append(value)
            elif isinstance(value, list):
                deps.extend(str(item) for item in value if item is not None)
        return list(dict.fromkeys(deps))
