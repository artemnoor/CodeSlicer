from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

from .alias_resolver import ImportAliasResolver
from .facts import FactSet
from .models import Binding, Evidence, Recipe
from .provider import ProviderResolver
from .symbol_table import SymbolTable


class BindingResolver:
    """Resolves aliases, re-exports, assignments, providers, fields, and destructuring."""

    def __init__(self, facts: FactSet, symbol_table: SymbolTable, recipes: Iterable[Recipe] = ()) -> None:
        self.facts = facts
        self.symbol_table = symbol_table
        self.recipes = list(recipes)
        self.alias_resolver = ImportAliasResolver(facts)
        self.provider_resolver = ProviderResolver(facts, self.recipes)
        self.bindings: Dict[str, Binding] = {}
        self.types: Dict[str, str] = {}
        self.return_objects: Dict[str, Dict[str, str]] = {}
        self.return_provider_targets: Dict[str, str] = {}
        self.diagnostics: List[str] = []

    def resolve(self) -> List[Binding]:
        self.provider_resolver.index()
        self.diagnostics.extend(self.provider_resolver.diagnostics)
        self._index_return_objects()
        self._bind_imports()
        self._bind_provider_factories()
        for _ in range(8):
            changed = self._bind_assignments_pass()
            if not changed:
                break
        return sorted(self.bindings.values(), key=lambda b: b.id or "")

    def resolve_name(self, name: object, seen: Optional[Set[str]] = None) -> str:
        if not isinstance(name, str):
            return str(name)
        if seen is None:
            seen = set()
        if name in seen:
            self._diag(f"binding cycle detected at {name!r}")
            return name
        seen.add(name)
        binding = self.bindings.get(name)
        if binding:
            return self.resolve_name(binding.target, seen)
        symbol = self.symbol_table.lookup(name)
        if symbol and symbol.qualified_name:
            return symbol.qualified_name
        return name

    def type_of(self, name: str) -> Optional[str]:
        resolved = self.resolve_name(name)
        if name in self.types:
            return self.types[name]
        if resolved in self.types:
            return self.types[resolved]
        provider = self.provider_resolver.target_for_provider_call(resolved) or self.provider_resolver.target_for_provider_call(name)
        if provider:
            return provider
        symbol = self.symbol_table.lookup(resolved) or self.symbol_table.lookup(name)
        if symbol and symbol.type_name:
            return symbol.type_name
        if isinstance(resolved, str) and resolved.startswith("instance:"):
            return resolved.split(":", 1)[1]
        return None

    def add_binding(self, binding: Binding) -> bool:
        existing = self.bindings.get(binding.source)
        if existing and existing.target == binding.target and existing.kind == binding.kind:
            return False
        if existing and existing.target != binding.target:
            if binding.confidence > existing.confidence:
                self._diag(
                    f"conflicting binding for {binding.source!r}: {existing.target!r} -> {binding.target!r}; kept higher confidence"
                )
                self.bindings[binding.source] = binding
                return True
            self._diag(
                f"conflicting binding for {binding.source!r}: {existing.target!r} vs {binding.target!r}; kept existing"
            )
            return False
        self.bindings[binding.source] = binding
        return True

    def _index_return_objects(self) -> None:
        for ret in self.facts.returns:
            if ret.value_kind == "object" or ret.object_keys:
                self.return_objects[ret.function] = {str(k): str(v) for k, v in ret.object_keys.items()}
            if ret.value_kind in {"provider_call", "call"} and ret.value is not None:
                provider = self.provider_resolver.target_for_provider_call(str(ret.value))
                if provider:
                    self.return_provider_targets[ret.function] = provider

    def _bind_imports(self) -> None:
        for imp in self.facts.imports:
            alias_resolution = self.alias_resolver.resolve(imp.target_name)
            self.diagnostics.extend(alias_resolution.diagnostics)
            ev = Evidence("import_alias", f"{imp.local_name} imports {imp.target_name}", imp.file, imp.line, imp.id)
            evidence = [ev] + alias_resolution.evidence
            kind = "IMPORT_ALIAS_AMBIGUOUS" if alias_resolution.ambiguous else "IMPORT_ALIAS"
            self.add_binding(Binding(imp.local_name, alias_resolution.target, kind, alias_resolution.confidence, evidence))

    def _bind_provider_factories(self) -> None:
        for assignment in self.facts.assignments:
            binding = self.provider_resolver.binding_for_factory(assignment)
            if not binding:
                continue
            self.types[assignment.target] = binding.target
            self.add_binding(binding)

    def _provider_target(self, function_name: str) -> Optional[str]:
        resolved = self.resolve_name(function_name)
        if function_name in self.return_provider_targets:
            return self.return_provider_targets[function_name]
        if resolved in self.return_provider_targets:
            return self.return_provider_targets[resolved]
        direct = self.provider_resolver.target_for_provider_call(function_name)
        if direct:
            return direct
        return self.provider_resolver.target_for_provider_call(resolved)

    def _bind_assignments_pass(self) -> bool:
        changed = False
        for assignment in self.facts.assignments:
            if self.provider_resolver.binding_for_factory(assignment):
                continue
            ev = Evidence("assignment", f"{assignment.target} assigned from {assignment.value}", assignment.file, assignment.line, assignment.id)
            target_value: Optional[str] = None
            kind = "ASSIGNMENT"

            if assignment.value_kind == "construct":
                target_value = str(assignment.value)
                kind = "CONSTRUCTS"
                self.types[assignment.target] = str(assignment.value)
            elif assignment.value_kind in {"provider_call"}:
                provider = self._provider_target(str(assignment.value))
                if provider:
                    target_value = provider
                    kind = "PROVIDER_CALL"
                    self.types[assignment.target] = provider
                else:
                    self._diag(f"unresolved provider call {assignment.value!r} for {assignment.target!r}")
            elif assignment.value_kind == "call":
                provider = self._provider_target(str(assignment.value))
                if provider:
                    target_value = provider
                    kind = "PROVIDER_CALL"
                    self.types[assignment.target] = provider
                else:
                    target_value = f"call:{assignment.value}"
                    kind = "CALL_RESULT"
            elif assignment.value_kind == "destructure":
                return_fn = str(assignment.value).replace("()", "")
                return_fn = self.resolve_name(return_fn)
                key = assignment.key or assignment.target
                member = self.return_objects.get(return_fn, {}).get(str(key))
                if not member:
                    member = self.return_objects.get(str(assignment.value).replace("()", ""), {}).get(str(key))
                if member:
                    target_value = self.resolve_name(member)
                    kind = "DESTRUCTURE_BINDING"
                else:
                    self._diag(f"unresolved destructuring key {key!r} from {return_fn!r}")
            else:
                if assignment.value is not None:
                    target_value = self.resolve_name(assignment.value)
                    kind = "FIELD_BINDING" if "." in assignment.target or "." in str(assignment.value) else "ASSIGNMENT"
                    source_type = self.type_of(str(assignment.value))
                    if source_type:
                        self.types[assignment.target] = source_type
                if assignment.type_name:
                    self.types[assignment.target] = assignment.type_name

            if target_value is not None:
                confidence = 0.95 if kind != "CALL_RESULT" else 0.8
                changed |= self.add_binding(Binding(assignment.target, target_value, kind, confidence, [ev]))
        return changed

    def _diag(self, message: str) -> None:
        if message not in self.diagnostics:
            self.diagnostics.append(message)
