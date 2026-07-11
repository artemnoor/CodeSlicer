"""Unknown external library detection for support pack research workflows."""
from __future__ import annotations

from pathlib import Path
from typing import List

from project_semantics_hygiene import DependencyClassifier, DependencyKind


_NON_RESEARCH_KINDS = {
    DependencyKind.STDLIB,
    DependencyKind.LOCAL,
    DependencyKind.KNOWN_COMMON_THIRD_PARTY,
    DependencyKind.BUILTIN_RUNTIME,
    DependencyKind.DEV_ONLY,
    DependencyKind.TYPE_ONLY,
}


def detect_unknown_libraries_core(path: str) -> List[str]:
    root = Path(path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path {path} does not exist")

    from impact_engine.inventory.scanner import scan_project_inventory

    inventory = scan_project_inventory(root)
    known_packs = _known_support_packs()
    classifier = DependencyClassifier()
    unknown: list[str] = []
    seen: set[tuple[str, str]] = set()

    imports_by_eco = inventory.external_imports_by_ecosystem or {"python": inventory.external_imports}
    declared_by_eco = {
        str(ecosystem): {str(dep) for dep in deps}
        for ecosystem, deps in (inventory.declared_dependencies_by_ecosystem or {}).items()
    }
    dev_by_eco = {
        str(ecosystem): {str(dep) for dep in deps}
        for ecosystem, deps in (inventory.dev_dependencies_by_ecosystem or {}).items()
    }
    local_by_eco = {
        str(ecosystem): {str(module) for module in modules}
        for ecosystem, modules in (inventory.local_modules_by_ecosystem or {}).items()
    }

    for ecosystem, imports in imports_by_eco.items():
        ecosystem = str(ecosystem)
        declared = declared_by_eco.get(ecosystem, set())
        dev = dev_by_eco.get(ecosystem, set())
        local = local_by_eco.get(ecosystem, set())
        for name in imports or []:
            name = str(name)
            key = (ecosystem, name)
            if key in seen:
                continue
            seen.add(key)
            if _has_support_pack(name, ecosystem, known_packs, classifier):
                continue
            classification = classifier.classify_dependency(
                name,
                ecosystem,
                declared_dependencies=declared,
                local_modules=local,
                dev_dependencies=dev,
            )
            if classification.kind in _NON_RESEARCH_KINDS:
                continue
            if classification.kind == DependencyKind.DECLARED_THIRD_PARTY:
                without_declared = classifier.classify_dependency(
                    name,
                    ecosystem,
                    declared_dependencies=set(),
                    local_modules=local,
                )
                if without_declared.kind == DependencyKind.KNOWN_COMMON_THIRD_PARTY:
                    continue
                unknown.append(_research_candidate_name(name, ecosystem, declared))
                continue
            if classification.requires_research:
                unknown.append(_research_candidate_name(name, ecosystem, declared))

    for ecosystem, declared in declared_by_eco.items():
        ecosystem = str(ecosystem)
        dev = dev_by_eco.get(ecosystem, set())
        local = local_by_eco.get(ecosystem, set())
        for name in declared:
            name = str(name)
            key = (ecosystem, name)
            if key in seen:
                continue
            seen.add(key)
            if _has_support_pack(name, ecosystem, known_packs, classifier):
                continue
            classification = classifier.classify_dependency(
                name,
                ecosystem,
                declared_dependencies=set(),
                local_modules=local,
                dev_dependencies=dev,
            )
            if classification.kind in _NON_RESEARCH_KINDS:
                continue
            if classification.requires_research:
                unknown.append(_research_candidate_name(name, ecosystem, declared))

    return sorted(_dedupe_preserve_name(unknown))


def _known_support_packs(root: str | Path = "support_packs") -> set[tuple[str | None, str]]:
    support_packs_dir = Path(root)
    known: set[tuple[str | None, str]] = set()
    if not support_packs_dir.exists():
        return known
    from impact_engine.support_packs.registry import list_local_support_packs

    for pack_path in list_local_support_packs(support_packs_dir):
        library = pack_path.parent.name
        ecosystem = pack_path.parent.parent.name if pack_path.parent.parent != support_packs_dir else None
        known.add((ecosystem, library))
        known.add((None, library))
    return known


def _has_support_pack(
    name: str,
    ecosystem: str,
    known_packs: set[tuple[str | None, str]],
    classifier: DependencyClassifier,
) -> bool:
    normalized = classifier._normalize_name(name, ecosystem)
    candidates = {name, normalized, name.replace("_", "-"), name.replace("-", "_")}
    return any((ecosystem, candidate) in known_packs or (None, candidate) in known_packs for candidate in candidates)


def _dedupe_preserve_name(names: list[str]) -> list[str]:
    seen = set()
    result = []
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def _research_candidate_name(name: str, ecosystem: str, declared: set[str]) -> str:
    if not declared:
        return name
    if ecosystem == "go":
        for dep in sorted(declared, key=len, reverse=True):
            if name == dep or name.startswith(dep.rstrip("/") + "/"):
                return dep
    if ecosystem in {"javascript", "typescript"}:
        for dep in declared:
            if name == dep or name.startswith(dep.rstrip("/") + "/"):
                return dep
    if ecosystem == "java":
        for dep in declared:
            group = dep.split(":", 1)[0]
            if name == group or name.startswith(group.rstrip(".") + "."):
                return dep
    return name
