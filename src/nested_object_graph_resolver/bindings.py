"""Receiver-chain resolution over the indexed object binding graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .index import FactIndex, normalize_path
from .models import Path, PathPart, PathResolution, path_to_string


@dataclass(frozen=True)
class AliasExpansion:
    path: Path
    confidence: float
    evidence: tuple[str, ...]
    warnings: tuple[str, ...] = tuple()
    rejected: bool = False


class ObjectBindingResolver:
    """Resolves language-neutral receiver chains to possible target types."""

    def __init__(self, index: FactIndex):
        self.index = index

    def resolve_receiver(
        self,
        *,
        scope: str,
        receiver_chain: Any,
        call_result: bool = False,
        provider_call: bool = False,
    ) -> PathResolution:
        owner = self.index.owner_class_for_scope(scope)
        path = normalize_path(receiver_chain)
        evidence = [f"call receiver chain: {path_to_string(path)}"]
        if not path:
            return PathResolution(evidence=evidence, warnings=["empty receiver chain"], status="unresolved")

        expansion = self.expand_aliases(scope, owner, path)
        evidence.extend(expansion.evidence)
        warnings = list(expansion.warnings)
        if expansion.rejected:
            return PathResolution(
                evidence=evidence,
                warnings=warnings,
                status="rejected",
                rejected=True,
            )
        if expansion.path != path:
            evidence.append(f"alias-expanded receiver chain: {path_to_string(expansion.path)}")
        path = expansion.path
        base_confidence = expansion.confidence

        # A provider call means the receiver expression is itself a factory or
        # container provider whose result should receive the final method call.
        if call_result or provider_call:
            provider_result = self._resolve_provider(path)
            if provider_result.types:
                provider_result.confidence *= base_confidence
                provider_result.evidence = evidence + provider_result.evidence
                provider_result.warnings = warnings + provider_result.warnings
                return provider_result
            # Continue with normal chain resolution as a fallback. This handles
            # container fields that are already bound to service instances.
            evidence.extend(provider_result.evidence)
            warnings.extend(provider_result.warnings)

        # Direct provider expression without explicit call_result is also useful
        # for facts like provider_bindings: container.order_service -> Service.
        direct_provider = self._resolve_provider(path)
        if direct_provider.types:
            direct_provider.confidence *= base_confidence
            direct_provider.evidence = evidence + direct_provider.evidence
            direct_provider.warnings = warnings + direct_provider.warnings
            return direct_provider

        result = self._resolve_field_chain(scope=scope, owner=owner, path=path)
        result.confidence *= base_confidence if result.confidence else base_confidence
        result.evidence = evidence + result.evidence
        result.warnings = warnings + result.warnings
        return result

    def expand_aliases(self, scope: str, owner: str | None, path: Path) -> AliasExpansion:
        confidence = 1.0
        evidence: list[str] = []
        warnings: list[str] = []
        seen: set[Path] = set()
        current = path

        for _ in range(32):
            if current in seen:
                warnings.append(f"alias cycle detected at {path_to_string(current)}")
                evidence.append("alias resolution stopped because a cycle was detected")
                return AliasExpansion(tuple(current), confidence * 0.2, tuple(evidence), tuple(warnings), True)
            seen.add(current)
            match = self._find_alias_match(scope, owner, current)
            if match is None:
                return AliasExpansion(tuple(current), confidence, tuple(evidence), tuple(warnings), False)
            alias, prefix_len = match
            suffix = current[prefix_len:]
            current = alias.target_path + suffix
            confidence *= alias.confidence
            evidence.extend(alias.evidence)
            evidence.append(
                f"alias: {path_to_string(alias.alias_path)} -> {path_to_string(alias.target_path)}"
            )
        warnings.append("alias expansion depth exceeded")
        return AliasExpansion(tuple(current), confidence * 0.2, tuple(evidence), tuple(warnings), True)

    def _find_alias_match(self, scope: str, owner: str | None, path: Path):
        aliases = list(self.index.aliases_by_scope.get(scope, []))
        if owner:
            aliases.extend(self.index.aliases_by_owner.get(owner, []))
        # Longest prefix wins so self.a.b aliases beat self.a aliases.
        aliases.sort(key=lambda item: len(item.alias_path), reverse=True)
        for alias in aliases:
            if len(path) >= len(alias.alias_path) and path[: len(alias.alias_path)] == alias.alias_path:
                return alias, len(alias.alias_path)
        return None

    def _resolve_provider(self, path: Path) -> PathResolution:
        bindings = self.index.provider_bindings.get(path, [])
        if not bindings:
            return PathResolution(
                evidence=[f"provider lookup: no provider binding for {path_to_string(path)}"],
                status="unresolved",
            )
        types = {binding.returns for binding in bindings}
        confidence = min(binding.confidence for binding in bindings)
        evidence: list[str] = []
        for binding in bindings:
            evidence.extend(binding.evidence)
            evidence.append(f"provider lookup: {path_to_string(binding.provider_path)} returns {binding.returns}")
        status = "resolved" if types else "unresolved"
        return PathResolution(types=types, confidence=confidence, evidence=evidence, status=status)

    def _resolve_field_chain(self, *, scope: str, owner: str | None, path: Path) -> PathResolution:
        if not owner and path[:1] == ("self",):
            return PathResolution(
                evidence=["cannot resolve self receiver because call scope has no owner class"],
                warnings=["missing owner class"],
                status="unresolved",
            )

        # `self` starts from the current class. A non-self first segment can be
        # a constructor/local param with known type, or a global provider path.
        if path[0] == "self":
            current_types = {owner} if owner else set()
            remaining = path[1:]
            evidence = [f"self type: {owner}"] if owner else []
            confidence = 1.0
        else:
            local_result = self._resolve_local_or_provider_start(owner, path)
            if local_result is not None:
                return local_result
            return PathResolution(
                evidence=[f"cannot resolve non-self receiver start: {path_to_string(path)}"],
                warnings=["non-self receiver has no binding"],
                status="unresolved",
            )

        if not remaining:
            return PathResolution(types=current_types, confidence=confidence, evidence=evidence, status="resolved")

        step = 0
        while step < len(remaining):
            part = remaining[step]
            if isinstance(part, tuple):
                return PathResolution(
                    evidence=evidence + [f"unexpected dict key without container: {part[1]!r}"],
                    warnings=["dict key access has no resolved container path"],
                    status="unresolved",
                )
            field_name = str(part)
            next_part = remaining[step + 1] if step + 1 < len(remaining) else None

            # Dict/map access: self.repositories['orders']
            if isinstance(next_part, tuple) and next_part[0] == "key":
                key_name = next_part[1]
                dict_candidates = []
                for current_type in sorted(current_types):
                    dict_candidates.extend(
                        self.index.dict_bindings.get((current_type, (field_name,), key_name), [])
                    )
                if not dict_candidates:
                    return PathResolution(
                        evidence=evidence
                        + [
                            f"dict lookup failed: no binding for {sorted(current_types)}.{field_name}[{key_name!r}]"
                        ],
                        warnings=["missing dict binding"],
                        status="unresolved",
                    )
                current_types = {binding.target_type for binding in dict_candidates}
                confidence = min(confidence, min(binding.confidence for binding in dict_candidates))
                for binding in dict_candidates:
                    evidence.extend(binding.evidence)
                    evidence.append(
                        f"dict binding: {binding.owner_type}.{'.'.join(binding.path)}[{binding.key_name!r}] -> {binding.target_type}"
                    )
                step += 2
                continue

            # Direct nested path binding: self.services.orders -> Service.
            nested = self._try_longest_direct_path(current_types, remaining, step)
            if nested is not None:
                new_types, consumed, nested_confidence, nested_evidence = nested
                current_types = new_types
                confidence = min(confidence, nested_confidence)
                evidence.extend(nested_evidence)
                step += consumed
                continue

            # Normal field binding: CurrentType.field -> TargetType.
            candidates = []
            for current_type in sorted(current_types):
                candidates.extend(self.index.field_bindings.get((current_type, (field_name,)), []))
            if not candidates:
                return PathResolution(
                    evidence=evidence
                    + [f"field lookup failed: no binding for {sorted(current_types)}.{field_name}"],
                    warnings=["missing field binding"],
                    status="unresolved",
                )
            current_types = {binding.target_type for binding in candidates}
            confidence = min(confidence, min(binding.confidence for binding in candidates))
            for binding in candidates:
                evidence.extend(binding.evidence)
                evidence.append(f"field binding: {binding.owner_type}.{field_name} -> {binding.target_type}")
            step += 1

        return PathResolution(types=current_types, confidence=confidence, evidence=evidence, status="resolved")

    def _try_longest_direct_path(
        self,
        current_types: set[str],
        remaining: Path,
        start: int,
    ) -> tuple[set[str], int, float, list[str]] | None:
        max_len = 0
        best_candidates = []
        best_path: tuple[str, ...] | None = None
        max_possible = len(remaining) - start
        for length in range(max_possible, 1, -1):
            parts = remaining[start : start + length]
            if any(isinstance(part, tuple) for part in parts):
                continue
            path = tuple(str(part) for part in parts)
            candidates = []
            for current_type in sorted(current_types):
                candidates.extend(self.index.field_bindings.get((current_type, path), []))
            if candidates:
                max_len = length
                best_candidates = candidates
                best_path = path
                break
        if not best_candidates or not best_path:
            return None
        new_types = {binding.target_type for binding in best_candidates}
        confidence = min(binding.confidence for binding in best_candidates)
        evidence: list[str] = []
        for binding in best_candidates:
            evidence.extend(binding.evidence)
            evidence.append(
                f"nested field binding: {binding.owner_type}.{'.'.join(binding.path)} -> {binding.target_type}"
            )
        return new_types, max_len, confidence, evidence

    def _resolve_local_or_provider_start(self, owner: str | None, path: Path) -> PathResolution | None:
        direct_provider = self._resolve_provider(path)
        if direct_provider.types:
            return direct_provider
        if owner and len(path) == 1 and isinstance(path[0], str):
            candidates = self.index.constructor_param_types.get((owner, path[0]), [])
            if candidates:
                return PathResolution(
                    types={binding.target_type for binding in candidates},
                    confidence=min(binding.confidence for binding in candidates),
                    evidence=[item for binding in candidates for item in binding.evidence]
                    + [f"local/constructor parameter {path[0]} has declared type"],
                    status="resolved",
                )
        return None
