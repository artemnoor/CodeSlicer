"""Local registry synchronization for analysis runs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from impact_engine.remote_registry.client import RegistryClient
from impact_engine.remote_registry.models import ResearchRequestRecord
from impact_engine.support_packs.detection import _has_support_pack, _known_support_packs, _research_candidate_name


def sync_registry_for_inventory(
    inventory_data: dict[str, Any],
    *,
    support_pack_root: str | Path = "support_packs",
    create_research_requests: bool = True,
    client: RegistryClient | None = None,
) -> dict[str, Any]:
    client = client or RegistryClient()
    known = _known_support_packs(support_pack_root) | _known_support_packs(".impact_engine/registry_cache/support_packs")

    classifier = _dependency_classifier()
    candidates = _candidate_dependencies(inventory_data, classifier)
    pulled: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []

    for ecosystem, name in candidates:
        if _has_support_pack(name, ecosystem, known, classifier):
            continue
        result = client.pull_support_pack(ecosystem, name)
        if result.get("status") == "ok":
            pulled.append({"ecosystem": ecosystem, "library": name, "source": result.get("source")})
            known.add((ecosystem, name.lower()))
            continue
        missing_item = {"ecosystem": ecosystem, "library": name}
        missing.append(missing_item)
        if create_research_requests:
            request_result = client.create_research_request(
                ResearchRequestRecord(ecosystem=ecosystem, library_name=name)
            )
            requests.append({"ecosystem": ecosystem, "library": name, "result": request_result})

    status = "ok" if not missing else "missing_packs"
    return {
        "status": status,
        "connection": client.connection_status(),
        "candidates": [{"ecosystem": eco, "library": name} for eco, name in candidates],
        "pulled": pulled,
        "missing": missing,
        "research_requests": requests,
    }


def _candidate_dependencies(inventory_data: dict[str, Any], classifier: Any) -> list[tuple[str, str]]:
    from project_semantics_hygiene import DependencyKind

    non_research = {
        DependencyKind.STDLIB,
        DependencyKind.LOCAL,
        DependencyKind.KNOWN_COMMON_THIRD_PARTY,
        DependencyKind.BUILTIN_RUNTIME,
        DependencyKind.DEV_ONLY,
        DependencyKind.TYPE_ONLY,
    }
    declared_by_eco = inventory_data.get("declared_dependencies_by_ecosystem") or {}
    dev_by_eco = inventory_data.get("dev_dependencies_by_ecosystem") or {}
    local_by_eco = inventory_data.get("local_modules_by_ecosystem") or {}
    imports_by_eco = inventory_data.get("external_imports_by_ecosystem") or {}
    if not imports_by_eco and inventory_data.get("external_imports"):
        imports_by_eco = {"python": inventory_data.get("external_imports") or []}

    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ecosystem, names in {**imports_by_eco, **declared_by_eco}.items():
        ecosystem = str(ecosystem)
        declared = {str(item) for item in declared_by_eco.get(ecosystem, []) or []}
        dev = {str(item) for item in dev_by_eco.get(ecosystem, []) or []}
        local = {str(item) for item in local_by_eco.get(ecosystem, []) or []}
        for raw_name in names or []:
            raw = str(raw_name)
            classification = classifier.classify_dependency(
                raw,
                ecosystem,
                declared_dependencies=declared,
                local_modules=local,
                dev_dependencies=dev,
            )
            if classification.kind in non_research:
                continue
            if not classification.requires_research and classification.kind != DependencyKind.DECLARED_THIRD_PARTY:
                continue
            name = _research_candidate_name(raw, ecosystem, declared).lower()
            key = (ecosystem, name)
            if key in seen:
                continue
            seen.add(key)
            result.append(key)
    return sorted(result)


def _dependency_classifier():
    from project_semantics_hygiene import DependencyClassifier

    return DependencyClassifier()
