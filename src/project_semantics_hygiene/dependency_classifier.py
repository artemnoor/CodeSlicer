from __future__ import annotations

import sys
from dataclasses import dataclass

from .models import DependencyClassification, DependencyKind
from .rule_pack import HygieneRulePack, default_rule_pack

_PY_FALLBACK_STDLIB = {
    "os",
    "sys",
    "json",
    "pathlib",
    "typing",
    "dataclasses",
    "uuid",
    "datetime",
    "asyncio",
    "collections",
    "functools",
    "itertools",
    "re",
    "math",
    "sqlite3",
    "logging",
    "subprocess",
    "email",
    "http",
    "urllib",
    "unittest",
    "enum",
    "abc",
    "contextlib",
    "inspect",
    "importlib",
    "tomllib",
    "hashlib",
    "tempfile",
    "shutil",
}


class DependencyClassifier:
    def __init__(self, rule_pack: HygieneRulePack | None = None):
        self.rule_pack = rule_pack or default_rule_pack()

    def classify_dependency(
        self,
        name: str,
        ecosystem: str,
        declared_dependencies: set[str] | None = None,
        local_modules: set[str] | None = None,
        dev_dependencies: set[str] | None = None,
        type_only: bool = False,
    ) -> DependencyClassification:
        eco = self._normalize_ecosystem(ecosystem)
        raw = name.strip().strip('"\'')
        normalized = self._normalize_name(raw, eco)
        declared_dependencies = set(declared_dependencies or set())
        local_modules = set(local_modules or set())
        dev_dependencies = set(dev_dependencies or set())
        reasons: list[str] = []

        if self._matches_any(normalized, local_modules, eco, raw):
            return DependencyClassification(
                name=raw,
                ecosystem=eco,
                kind=DependencyKind.LOCAL,
                confidence=0.97,
                reasons=["matched local module name"],
                declared=False,
                local=True,
                requires_research=False,
            )

        if self._is_stdlib(normalized, eco):
            return DependencyClassification(
                name=raw,
                ecosystem=eco,
                kind=DependencyKind.STDLIB,
                confidence=0.96,
                reasons=[f"matched {eco} stdlib/runtime allow-list"],
                declared=False,
                local=False,
                requires_research=False,
            )

        if self._is_builtin_runtime(normalized, eco):
            return DependencyClassification(
                name=raw,
                ecosystem=eco,
                kind=DependencyKind.BUILTIN_RUNTIME,
                confidence=0.95,
                reasons=[f"matched {eco} builtin runtime module"],
                declared=False,
                local=False,
                requires_research=False,
            )

        if type_only:
            return DependencyClassification(
                name=raw,
                ecosystem=eco,
                kind=DependencyKind.TYPE_ONLY,
                confidence=0.90,
                reasons=["dependency usage was marked type-only"],
                declared=self._matches_any(normalized, declared_dependencies, eco, raw),
                local=False,
                requires_research=False,
            )

        if self._matches_any(normalized, dev_dependencies, eco, raw):
            return DependencyClassification(
                name=raw,
                ecosystem=eco,
                kind=DependencyKind.DEV_ONLY,
                confidence=0.92,
                reasons=["matched declared development dependency"],
                declared=True,
                local=False,
                requires_research=False,
            )

        if self._matches_any(normalized, declared_dependencies, eco, raw):
            return DependencyClassification(
                name=raw,
                ecosystem=eco,
                kind=DependencyKind.DECLARED_THIRD_PARTY,
                confidence=0.94,
                reasons=["matched declared third-party dependency"],
                declared=True,
                local=False,
                requires_research=False,
            )

        known_match = self._known_common_match(normalized, eco)
        if known_match:
            return DependencyClassification(
                name=raw,
                ecosystem=eco,
                kind=DependencyKind.KNOWN_COMMON_THIRD_PARTY,
                confidence=0.86,
                reasons=[f"matched known common third-party dependency '{known_match}'"],
                declared=False,
                local=False,
                requires_research=False,
            )

        reasons.append("not stdlib/local/declared/dev/type-only/known-common")
        return DependencyClassification(
            name=raw,
            ecosystem=eco,
            kind=DependencyKind.UNKNOWN_THIRD_PARTY,
            confidence=0.70,
            reasons=reasons,
            declared=False,
            local=False,
            requires_research=True,
        )

    def _normalize_ecosystem(self, ecosystem: str) -> str:
        e = ecosystem.strip().lower()
        aliases = {
            "js": "javascript",
            "node": "javascript",
            "nodejs": "javascript",
            "npm": "javascript",
            "ts": "typescript",
            "tsx": "typescript",
            "py": "python",
            "golang": "go",
            "jvm": "java",
        }
        return aliases.get(e, e)

    def _normalize_name(self, name: str, ecosystem: str) -> str:
        n = name.strip()
        if ecosystem == "python":
            return n.split(".")[0].replace("-", "_").lower()
        if ecosystem in {"javascript", "typescript"}:
            n = n.removeprefix("node:")
            if n.startswith("@"):
                parts = n.split("/")
                return "/".join(parts[:2]) if len(parts) >= 2 else n
            return n.split("/")[0]
        if ecosystem == "java":
            if n.startswith("java."):
                return "java"
            if n.startswith("javax."):
                return "javax"
            if n.startswith("org.springframework"):
                return "org.springframework"
            parts = n.split(".")
            if len(parts) >= 2:
                return ".".join(parts[:2])
            return n
        if ecosystem == "go":
            # Keep stdlib imports as-is; third-party module matching is handled
            # with prefix logic against declared deps.
            return n
        return n.split(".")[0]

    def _matches_any(self, normalized: str, candidates: set[str], ecosystem: str, raw: str) -> bool:
        if not candidates:
            return False
        normalized_candidates = {self._normalize_name(c, ecosystem) for c in candidates}
        raw_candidates = {c.strip() for c in candidates}
        if normalized in normalized_candidates or raw in raw_candidates:
            return True
        if ecosystem == "go":
            return any(raw == c or raw.startswith(c.rstrip("/") + "/") for c in raw_candidates)
        if ecosystem == "java":
            return any(raw == c or raw.startswith(c.rstrip(".") + ".") for c in raw_candidates)
        if ecosystem in {"javascript", "typescript"}:
            return any(raw == c or raw.startswith(c.rstrip("/") + "/") for c in raw_candidates)
        return False

    def _is_stdlib(self, normalized: str, ecosystem: str) -> bool:
        overrides = set(self.rule_pack.stdlib_overrides.get(ecosystem, []))
        if ecosystem == "python":
            stdlib = set(getattr(sys, "stdlib_module_names", set()) or set()) | _PY_FALLBACK_STDLIB | overrides
            return normalized in stdlib
        if ecosystem == "go":
            return any(normalized == item or normalized.startswith(item.rstrip("/") + "/") for item in overrides) and "." not in normalized.split("/")[0]
        if ecosystem == "java":
            return normalized in {"java", "javax"} or normalized in overrides
        return False

    def _is_builtin_runtime(self, normalized: str, ecosystem: str) -> bool:
        if ecosystem in {"javascript", "typescript"}:
            return normalized in set(self.rule_pack.stdlib_overrides.get(ecosystem, []))
        return False

    def _known_common_match(self, normalized: str, ecosystem: str) -> str | None:
        candidates = self.rule_pack.known_common_dependencies.get(ecosystem, [])
        for candidate in candidates:
            c = self._normalize_name(candidate, ecosystem)
            if normalized == c:
                return candidate
            if ecosystem == "go" and (normalized == candidate or normalized.startswith(candidate.rstrip("/") + "/")):
                return candidate
            if ecosystem == "java" and (normalized == candidate or normalized.startswith(candidate.rstrip(".") + ".")):
                return candidate
        return None
