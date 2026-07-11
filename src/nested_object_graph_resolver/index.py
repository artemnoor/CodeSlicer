"""Fact indexing and path normalization utilities."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .models import (
    AliasBinding,
    DictEntryBinding,
    Path,
    PathPart,
    ProviderBinding,
    TypeBinding,
    clamp_confidence,
    path_to_string,
)

_LIST_KEYS = {
    "classes",
    "methods",
    "constructor_params",
    "assignments",
    "field_bindings",
    "dict_bindings",
    "provider_bindings",
    "returns",
    "calls",
    "aliases",
}

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BRACKET_RE = re.compile(r"\[\s*(['\"])(.*?)\1\s*\]")


def validate_input(input_data: Any) -> tuple[bool, list[str]]:
    if not isinstance(input_data, dict):
        return False, ["input_data must be a JSON-compatible dict"]
    errors: list[str] = []
    for key in _LIST_KEYS:
        if key in input_data and not isinstance(input_data[key], list):
            errors.append(f"{key} must be a list")
    if "options" in input_data and not isinstance(input_data["options"], dict):
        errors.append("options must be a dict")
    return not errors, errors


def fact_evidence(fact: dict[str, Any], fallback: str) -> tuple[str, ...]:
    evidence = fact.get("evidence")
    if isinstance(evidence, list):
        items = [str(item) for item in evidence if item is not None]
        return tuple(items or [fallback])
    if isinstance(evidence, str):
        return (evidence,)
    return (fallback,)


def normalize_path(expr: Any) -> Path:
    """Normalize a string expression or receiver_chain into hashable path parts.

    String examples:
      self.repository -> ("self", "repository")
      providers['billing']() -> ("providers", ("key", "billing"))
    Receiver chain example:
      ["self", "repositories", {"key": "orders"}]
    """

    if expr is None:
        return tuple()
    if isinstance(expr, tuple):
        return expr
    if isinstance(expr, list):
        parts: list[PathPart] = []
        for item in expr:
            if isinstance(item, dict) and "key" in item:
                parts.append(("key", str(item["key"])))
            elif item is not None:
                text = str(item)
                nested = normalize_path(text)
                if len(nested) > 1 or (nested and ("." in text or "[" in text)):
                    parts.extend(nested)
                else:
                    parts.append(text)
        return tuple(parts)
    text = str(expr).strip()
    if text.endswith("()"):
        text = text[:-2].strip()
    text = text.replace('"', "'")
    if not text:
        return tuple()

    parts: list[PathPart] = []
    index = 0
    while index < len(text):
        ch = text[index]
        if ch in ". \t\n\r":
            index += 1
            continue
        if ch == "[":
            match = _BRACKET_RE.match(text, index)
            if match:
                parts.append(("key", match.group(2)))
                index = match.end()
                continue
            # Unsupported dynamic key expression. Keep a sentinel string so the
            # resolver can reject or mark it suspicious rather than guessing.
            close = text.find("]", index)
            raw = text[index + 1 : close if close >= 0 else len(text)].strip()
            parts.append(("key", raw or "<dynamic>"))
            index = close + 1 if close >= 0 else len(text)
            continue
        match = _IDENTIFIER_RE.match(text, index)
        if match:
            parts.append(match.group(0))
            index = match.end()
            continue
        index += 1
    return tuple(parts)


def path_without_self(path: Path) -> tuple[str, ...] | None:
    if not path or path[0] != "self":
        return None
    result: list[str] = []
    for part in path[1:]:
        if isinstance(part, tuple):
            return None
        result.append(part)
    return tuple(result)


def split_dict_target(path: Path) -> tuple[tuple[str, ...] | None, str | None]:
    """Return (container path after self, literal key) for self.x['key']."""

    if not path or path[0] != "self":
        return None, None
    if not path[-1:] or not isinstance(path[-1], tuple):
        return None, None
    container: list[str] = []
    for part in path[1:-1]:
        if isinstance(part, tuple):
            return None, None
        container.append(part)
    return tuple(container), path[-1][1]


def is_pathlike(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if value in {"self", "this"}:
        return True
    return "." in value or "[" in value


def is_alias_expression(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if text.startswith(("{", "[", "(", "`", '"', "'")):
        return False
    if "(" in text or ")" in text or ":" in text or "," in text:
        return False
    return is_pathlike(text)


@dataclass
class FactIndex:
    """Indexes normalized facts for deterministic resolution."""

    raw: dict[str, Any]
    classes: dict[str, dict[str, Any]] = field(default_factory=dict)
    class_methods: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    method_ids: set[str] = field(default_factory=set)
    constructor_param_types: dict[tuple[str, str], list[TypeBinding]] = field(default_factory=lambda: defaultdict(list))
    field_bindings: dict[tuple[str, tuple[str, ...]], list[TypeBinding]] = field(default_factory=lambda: defaultdict(list))
    dict_bindings: dict[tuple[str, tuple[str, ...], str], list[DictEntryBinding]] = field(default_factory=lambda: defaultdict(list))
    provider_bindings: dict[Path, list[ProviderBinding]] = field(default_factory=lambda: defaultdict(list))
    aliases_by_scope: dict[str, list[AliasBinding]] = field(default_factory=lambda: defaultdict(list))
    aliases_by_owner: dict[str, list[AliasBinding]] = field(default_factory=lambda: defaultdict(list))
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def build(cls, raw: dict[str, Any]) -> "FactIndex":
        index = cls(raw=raw)
        index._index_classes_and_methods()
        index._index_constructor_params()
        index._index_field_bindings()
        index._derive_bindings_from_assignments()
        index._index_dict_bindings()
        index._index_provider_bindings()
        index._index_return_bindings()
        index._index_aliases()
        return index

    def all_bindings_as_dicts(self) -> list[dict[str, Any]]:
        seen: set[tuple[Any, ...]] = set()
        output: list[dict[str, Any]] = []
        for binding_list in self.field_bindings.values():
            for binding in binding_list:
                marker = ("field",) + binding.key()
                if marker not in seen:
                    seen.add(marker)
                    item = binding.to_dict()
                    item["kind"] = "FIELD_BINDING"
                    output.append(item)
        for binding_list in self.dict_bindings.values():
            for binding in binding_list:
                marker = ("dict",) + binding.key()
                if marker not in seen:
                    seen.add(marker)
                    item = binding.to_dict()
                    item["kind"] = "DICT_ENTRY_BINDING"
                    output.append(item)
        for binding_list in self.provider_bindings.values():
            for binding in binding_list:
                marker = ("provider", binding.provider_path, binding.returns)
                if marker not in seen:
                    seen.add(marker)
                    item = binding.to_dict()
                    item["kind"] = "PROVIDER_BINDING"
                    output.append(item)
        for alias_list in list(self.aliases_by_scope.values()) + list(self.aliases_by_owner.values()):
            for binding in alias_list:
                marker = ("alias",) + binding.key()
                if marker not in seen:
                    seen.add(marker)
                    item = binding.to_dict()
                    item["kind"] = "ALIAS_BINDING"
                    output.append(item)
        return sorted(output, key=lambda item: (item.get("kind", ""), str(item)))

    def owner_class_for_scope(self, scope: str | None) -> str | None:
        if not scope:
            return None
        # Prefer known classes and longest prefix to support nested packages.
        candidates = [class_id for class_id in self.classes if scope == class_id or scope.startswith(class_id + ".")]
        if candidates:
            return max(candidates, key=len)
        if "." in scope:
            return scope.rsplit(".", 1)[0]
        return None

    def method_name_for_scope(self, scope: str | None) -> str | None:
        if not scope:
            return None
        owner = self.owner_class_for_scope(scope)
        if owner and scope.startswith(owner + "."):
            return scope[len(owner) + 1 :]
        if "." in scope:
            return scope.rsplit(".", 1)[1]
        return scope

    def class_has_method(self, class_id: str, method_name: str) -> bool:
        return method_name in self.class_methods.get(class_id, set())

    def _index_classes_and_methods(self) -> None:
        for fact in self.raw.get("classes", []):
            if not isinstance(fact, dict) or not fact.get("id"):
                self._diag("ignored_class", "class fact without id", fact)
                continue
            class_id = str(fact["id"])
            self.classes[class_id] = fact
            for method in fact.get("methods", []) or []:
                name = str(method)
                self.class_methods[class_id].add(name)
                self.method_ids.add(f"{class_id}.{name}")
        for fact in self.raw.get("methods", []):
            if not isinstance(fact, dict):
                continue
            class_id = fact.get("class") or fact.get("owner")
            name = fact.get("name")
            method_id = fact.get("id")
            if method_id:
                self.method_ids.add(str(method_id))
            if class_id and name:
                self.class_methods[str(class_id)].add(str(name))
                self.method_ids.add(f"{class_id}.{name}")

    def _index_constructor_params(self) -> None:
        for fact in self.raw.get("constructor_params", []):
            if not isinstance(fact, dict):
                continue
            class_id = fact.get("class")
            param = fact.get("param")
            target_type = fact.get("type") or fact.get("target_type")
            if not class_id or not param or not target_type:
                self._diag("ignored_constructor_param", "constructor_param requires class, param and type", fact)
                continue
            targets = target_type if isinstance(target_type, list) else [target_type]
            for item in targets:
                binding = TypeBinding(
                    owner_type=str(class_id),
                    path=(str(param),),
                    target_type=str(item),
                    confidence=clamp_confidence(fact.get("confidence"), 0.95),
                    source="DECLARED",
                    evidence=fact_evidence(fact, f"{param} annotated as {item}"),
                )
                self.constructor_param_types[(str(class_id), str(param))].append(binding)

    def _index_field_bindings(self) -> None:
        for fact in self.raw.get("field_bindings", []):
            if not isinstance(fact, dict):
                continue
            owner_type = fact.get("owner_type") or fact.get("class")
            field_name = fact.get("field") or fact.get("path")
            target_type = fact.get("target_type") or fact.get("type")
            if not owner_type or not field_name or not target_type:
                self._diag("ignored_field_binding", "field_binding requires owner_type, field and target_type", fact)
                continue
            path = tuple(str(part) for part in str(field_name).split(".") if part)
            targets = target_type if isinstance(target_type, list) else [target_type]
            for item in targets:
                self._add_field_binding(
                    TypeBinding(
                        owner_type=str(owner_type),
                        path=path,
                        target_type=str(item),
                        confidence=clamp_confidence(fact.get("confidence"), 0.9),
                        source="DECLARED",
                        evidence=fact_evidence(fact, f"{owner_type}.{'.'.join(path)} declared as {item}"),
                    )
                )

    def _derive_bindings_from_assignments(self) -> None:
        for fact in self.raw.get("assignments", []):
            if not isinstance(fact, dict):
                continue
            scope = str(fact.get("scope") or "")
            owner = self.owner_class_for_scope(scope)
            if not owner:
                self._diag("ignored_assignment", "assignment scope does not identify an owner class", fact)
                continue
            target_path = normalize_path(fact.get("target"))
            value = fact.get("value")
            value_path = normalize_path(value) if is_pathlike(value) else tuple()
            self_path = path_without_self(target_path)
            # self.field = constructor_param  -> field binding
            if self_path and isinstance(value, str):
                param_bindings = self.constructor_param_types.get((owner, value), [])
                for param_binding in param_bindings:
                    self._add_field_binding(
                        TypeBinding(
                            owner_type=owner,
                            path=self_path,
                            target_type=param_binding.target_type,
                            confidence=min(
                                clamp_confidence(fact.get("confidence"), 0.95),
                                param_binding.confidence,
                            ),
                            source="INFERRED",
                            evidence=tuple(fact_evidence(fact, f"{scope}: {path_to_string(target_path)} = {value}"))
                            + param_binding.evidence,
                        )
                    )
            # self.alias = self.target or local_alias = self.target -> alias binding.
            if target_path and value_path and target_path != value_path and is_alias_expression(value):
                alias = AliasBinding(
                    scope=scope,
                    owner_type=owner,
                    alias_path=target_path,
                    target_path=value_path,
                    confidence=clamp_confidence(fact.get("confidence"), 0.85),
                    source="INFERRED",
                    evidence=fact_evidence(fact, f"{scope}: {path_to_string(target_path)} = {path_to_string(value_path)}"),
                )
                self._add_alias(alias)

    def _index_dict_bindings(self) -> None:
        for fact in self.raw.get("dict_bindings", []):
            if not isinstance(fact, dict):
                continue
            scope = str(fact.get("scope") or "")
            owner = self.owner_class_for_scope(scope)
            target_path = normalize_path(fact.get("target"))
            if not owner or not target_path:
                self._diag("ignored_dict_binding", "dict_binding requires scope with owner and target", fact)
                continue
            # Form 1: target self.repositories, entries/value_types by literal key.
            self_path = path_without_self(target_path)
            if self_path:
                entries = fact.get("entries") if isinstance(fact.get("entries"), dict) else {}
                value_types = fact.get("value_types") if isinstance(fact.get("value_types"), dict) else {}
                for key_name in sorted(set(entries) | set(value_types)):
                    target_type = value_types.get(key_name)
                    if not target_type and isinstance(entries.get(key_name), str):
                        param_bindings = self.constructor_param_types.get((owner, entries[key_name]), [])
                        if param_bindings:
                            target_type = [binding.target_type for binding in param_bindings]
                        else:
                            resolved_path_types = self._resolve_assignment_value_path(owner, entries[key_name])
                            if resolved_path_types:
                                target_type = resolved_path_types
                    if not target_type:
                        self._diag("ignored_dict_entry", f"dict entry {key_name!r} has no known value type", fact)
                        continue
                    targets = target_type if isinstance(target_type, list) else [target_type]
                    for item in targets:
                        self._add_dict_binding(
                            DictEntryBinding(
                                owner_type=owner,
                                path=self_path,
                                key_name=str(key_name),
                                target_type=str(item),
                                confidence=clamp_confidence(fact.get("confidence"), 0.8),
                                source="INFERRED",
                                evidence=fact_evidence(
                                    fact,
                                    f"{scope}: {path_to_string(target_path)}[{key_name!r}] -> {item}",
                                ),
                            )
                        )
                continue
            # Form 2: target self.providers['order_service'], value order_service.
            container, key_name = split_dict_target(target_path)
            if container and key_name:
                value = fact.get("value")
                target_type = fact.get("type") or fact.get("target_type")
                if not target_type and isinstance(value, str):
                    param_bindings = self.constructor_param_types.get((owner, value), [])
                    if param_bindings:
                        target_type = [binding.target_type for binding in param_bindings]
                if not target_type:
                    self._diag("ignored_dict_entry", "separate dict assignment has no value type", fact)
                    continue
                targets = target_type if isinstance(target_type, list) else [target_type]
                for item in targets:
                    self._add_dict_binding(
                        DictEntryBinding(
                            owner_type=owner,
                            path=container,
                            key_name=key_name,
                            target_type=str(item),
                            confidence=clamp_confidence(fact.get("confidence"), 0.8),
                            source="INFERRED",
                            evidence=fact_evidence(fact, f"{scope}: {path_to_string(target_path)} = {value}"),
                        )
                    )

    def _index_provider_bindings(self) -> None:
        for fact in self.raw.get("provider_bindings", []):
            if not isinstance(fact, dict):
                continue
            provider = fact.get("provider")
            returns = fact.get("returns") or fact.get("type")
            if not provider or not returns:
                self._diag("ignored_provider_binding", "provider_binding requires provider and returns", fact)
                continue
            targets = returns if isinstance(returns, list) else [returns]
            for item in targets:
                self._add_provider_binding(
                    ProviderBinding(
                        provider_path=normalize_path(provider),
                        returns=str(item),
                        confidence=clamp_confidence(fact.get("confidence"), 0.82),
                        source="DECLARED",
                        evidence=fact_evidence(fact, f"provider {provider} returns {item}"),
                    )
                )

    def _index_return_bindings(self) -> None:
        for fact in self.raw.get("returns", []):
            if not isinstance(fact, dict):
                continue
            scope = fact.get("scope")
            returns = fact.get("returns") or fact.get("type")
            if not scope or not returns:
                self._diag("ignored_return_binding", "return binding requires scope and returns", fact)
                continue
            targets = returns if isinstance(returns, list) else [returns]
            for item in targets:
                self._add_provider_binding(
                    ProviderBinding(
                        provider_path=normalize_path(scope),
                        returns=str(item),
                        confidence=clamp_confidence(fact.get("confidence"), 0.8),
                        source="INFERRED",
                        evidence=fact_evidence(fact, f"{scope} returns {item}"),
                    )
                )

    def _index_aliases(self) -> None:
        for fact in self.raw.get("aliases", []):
            if not isinstance(fact, dict):
                continue
            scope = str(fact.get("scope") or "")
            owner = self.owner_class_for_scope(scope)
            alias_path = normalize_path(fact.get("alias"))
            target_path = normalize_path(fact.get("target"))
            if not alias_path or not target_path:
                self._diag("ignored_alias", "alias requires alias and target", fact)
                continue
            self._add_alias(
                AliasBinding(
                    scope=scope,
                    owner_type=owner,
                    alias_path=alias_path,
                    target_path=target_path,
                    confidence=clamp_confidence(fact.get("confidence"), 0.88),
                    source="DECLARED",
                    evidence=fact_evidence(fact, f"{scope}: {path_to_string(alias_path)} aliases {path_to_string(target_path)}"),
                )
            )

    def _add_field_binding(self, binding: TypeBinding) -> None:
        key = (binding.owner_type, binding.path)
        if all(existing.key() != binding.key() for existing in self.field_bindings[key]):
            self.field_bindings[key].append(binding)

    def _add_dict_binding(self, binding: DictEntryBinding) -> None:
        key = (binding.owner_type, binding.path, binding.key_name)
        if all(existing.key() != binding.key() for existing in self.dict_bindings[key]):
            self.dict_bindings[key].append(binding)

    def _add_provider_binding(self, binding: ProviderBinding) -> None:
        if all(existing.key() != binding.key() for existing in self.provider_bindings[binding.provider_path]):
            self.provider_bindings[binding.provider_path].append(binding)

    def _add_alias(self, binding: AliasBinding) -> None:
        if binding.alias_path and binding.alias_path[0] == "self" and binding.owner_type:
            collection = self.aliases_by_owner[binding.owner_type]
        else:
            collection = self.aliases_by_scope[binding.scope]
        if all(existing.key() != binding.key() for existing in collection):
            collection.append(binding)

    def _resolve_assignment_value_path(self, owner: str, value: str) -> list[str]:
        """Resolve dict-entry values like ``uow.orders`` to concrete types.

        The source collector intentionally stays language-neutral and records
        the expression text. The index already knows constructor parameter
        types and field bindings, so resolving the path here keeps this generic
        for any parser that emits the same facts.
        """

        path = normalize_path(value)
        if not path or not isinstance(path[0], str):
            return []
        candidates = self.constructor_param_types.get((owner, path[0]), [])
        current_types = {binding.target_type for binding in candidates}
        if not current_types:
            return []
        for part in path[1:]:
            if isinstance(part, tuple):
                return []
            next_types: set[str] = set()
            for current_type in current_types:
                for binding in self.field_bindings.get((current_type, (str(part),)), []):
                    next_types.add(binding.target_type)
            if not next_types:
                return []
            current_types = next_types
        return sorted(current_types)

    def _diag(self, code: str, message: str, fact: Any | None = None) -> None:
        item: dict[str, Any] = {"code": code, "message": message}
        if fact is not None:
            item["fact"] = fact
        self.diagnostics.append(item)
