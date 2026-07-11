from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .facts import FactSet
from .models import Evidence, ExportFact


@dataclass
class AliasResolution:
    target: str
    confidence: float
    evidence: List[Evidence] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)
    ambiguous: bool = False


class ImportAliasResolver:
    """Resolves import aliases through deterministic re-export chains."""

    def __init__(self, facts: FactSet) -> None:
        self.facts = facts
        self._exports: Dict[str, List[ExportFact]] = {}
        self._build_index()

    def _build_index(self) -> None:
        for exp in self.facts.exports:
            for key in self._export_keys(exp):
                self._exports.setdefault(key, []).append(exp)

    def _export_keys(self, exp: ExportFact) -> List[str]:
        keys: List[str] = []
        if exp.module:
            keys.append(f"{exp.module}.{exp.name}")
        keys.append(exp.name)
        return list(dict.fromkeys(keys))

    def resolve(self, target: str) -> AliasResolution:
        evidence: List[Evidence] = []
        diagnostics: List[str] = []
        resolved, ambiguous = self._resolve_chain(target, evidence, diagnostics, set(), True)
        confidence = 0.55 if ambiguous else (0.98 if evidence else 1.0)
        return AliasResolution(resolved, confidence, evidence, diagnostics, ambiguous)

    def _resolve_chain(
        self,
        target: str,
        evidence: List[Evidence],
        diagnostics: List[str],
        seen: Set[str],
        allow_fallback: bool,
    ) -> Tuple[str, bool]:
        if target in seen:
            diagnostics.append(f"re-export cycle detected at {target!r}")
            return target, True
        seen.add(target)

        exports = self._exports.get(target, [])
        if not exports and allow_fallback and "." in target:
            # Fallback only for the original import target. Re-export targets are
            # treated as canonical symbols unless an exact export exists.
            exports = self._exports.get(target.rsplit(".", 1)[-1], [])

        if not exports:
            return target, False

        unique_targets = sorted({exp.target or self._default_target(exp) for exp in exports})
        if len(unique_targets) != 1:
            diagnostics.append(f"ambiguous re-export for {target!r}: {unique_targets}")
            for exp in exports:
                evidence.append(self._evidence(exp, target))
            return target, True

        exp = sorted(exports, key=lambda item: item.id or "")[0]
        next_target = unique_targets[0]
        evidence.append(self._evidence(exp, target))
        if next_target == target:
            return target, False
        return self._resolve_chain(next_target, evidence, diagnostics, seen, False)

    def _default_target(self, exp: ExportFact) -> str:
        return f"{exp.module}.{exp.name}" if exp.module else exp.name

    def _evidence(self, exp: ExportFact, key: str) -> Evidence:
        target = exp.target or self._default_target(exp)
        return Evidence("re_export", f"{key} re-exports {target}", exp.file, exp.line, exp.id)
