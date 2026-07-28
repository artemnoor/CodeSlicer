"""Evidence-gated plugin selection and deterministic execution plans."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

from .contracts import PluginContext, PluginDiagnostic
from .registry import PluginRegistry, discover_plugin_registry


@dataclass
class PluginSelectionPlan:
    selected_language_ids: list[str] = field(default_factory=list)
    selected_framework_ids: list[str] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)
    cache_keys: dict[str, str] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=dict)
    registry: PluginRegistry | None = None

    @property
    def languages(self) -> list[str]:
        result = []
        for plugin_id in self.selected_language_ids:
            manifest = self.registry.manifests[plugin_id] if self.registry else None
            if manifest and manifest.language not in result:
                result.append(manifest.language)
        return result

    def selected_ids(self) -> tuple[str, ...]:
        return tuple(self.selected_language_ids + self.selected_framework_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": [{"id": key, "kind": self.registry.manifests[key].kind, "language": self.registry.manifests[key].language, "version": self.versions.get(key), "cache_key": self.cache_keys.get(key), "capabilities": dict(self.registry.manifests[key].capabilities)} for key in self.selected_ids()] if self.registry else [],
            "rejected": list(self.rejected),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def _inventory_values(inventory: dict[str, Any], key: str, language: str) -> set[str]:
    by_eco = inventory.get(f"{key}_by_ecosystem") or {}
    values = by_eco.get(language) or []
    if values:
        return {str(value).lower() for value in values}
    return {str(value).lower() for value in inventory.get(key, []) or []}


def _matches(value: str, candidates: set[str]) -> bool:
    normalized = value.lower().replace("_", "-")
    return any(normalized == candidate.replace("_", "-") or normalized.startswith(candidate.replace("_", "-") + "/") for candidate in candidates)


def _language_selected(manifest, inventory: dict[str, Any]) -> tuple[bool, str]:
    languages = {str(value).lower() for value in inventory.get("languages", [])}
    extensions = {Path(str(value)).suffix.lower() for value in inventory.get("files", [])}
    manifests = {Path(str(value)).name.lower() for value in inventory.get("package_manifests", [])}
    if manifest.language.lower() not in languages:
        return False, "language not present in inventory"
    extension_match = bool(extensions.intersection(manifest.file_extensions))
    manifest_match = bool(manifests.intersection(manifest.manifest_files))
    if manifest.file_extensions and not extension_match and not manifest_match:
        # A manifest is allowed to confirm a language only when inventory has
        # already identified that language. This preserves mixed JS/TS
        # projects whose package manifest is the only language evidence while
        # avoiding activation from a shared manifest alone.
        return False, "no matching extension or manifest"
    return True, "language extension/manifest evidence"


def _framework_selected(manifest, inventory: dict[str, Any], *, explicit_local: bool = False) -> tuple[bool, str, list[str]]:
    if explicit_local:
        return True, "explicit project-local pack", ["project_local_pack"]
    activation = dict(manifest.activation)
    deps = _inventory_values(inventory, "declared_dependencies", manifest.language)
    imports = _inventory_values(inventory, "external_imports", manifest.language)
    evidence: list[str] = []
    for name in activation.get("dependencies", []) or []:
        if _matches(str(name), deps):
            evidence.append(f"dependency:{name}")
    for name in activation.get("imports", []) or []:
        if _matches(str(name), imports):
            evidence.append(f"import:{name}")
    if evidence:
        supported = tuple(manifest.supported_versions or ())
        known_versions = inventory.get("dependency_versions_by_ecosystem", {}).get(manifest.language, {}) or {}
        if supported and known_versions:
            matched_versions = [str(version) for dependency, version in known_versions.items() if _matches(str(dependency), deps)]
            if matched_versions and not any(_version_matches(version, supported) for version in matched_versions):
                return False, "dependency version is outside supported_versions", evidence
        return True, "strong dependency/import evidence", evidence
    return False, "no declared dependency or confirmed import evidence", []


def _version_matches(version: str, supported: tuple[str, ...]) -> bool:
    """Match the limited PEP 440/semver subset used by pack manifests."""

    def parse(value: str) -> tuple[int, ...] | None:
        match = re.match(r"^\s*[v=]*(\d+(?:\.\d+)*)(?:[-+].*)?\s*$", value)
        return tuple(int(part) for part in match.group(1).split(".")) if match else None

    actual = parse(version)
    if actual is None:
        return False

    def compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
        width = max(len(left), len(right))
        a = left + (0,) * (width - len(left))
        b = right + (0,) * (width - len(right))
        return (a > b) - (a < b)

    for raw_rule in supported:
        rule = str(raw_rule).strip()
        if not rule:
            continue
        clauses = [item.strip() for item in rule.split(",") if item.strip()]
        matched = True
        for clause in clauses:
            wildcard = clause.lower().replace("*", "x")
            if wildcard.endswith(".x"):
                prefix = parse(wildcard[:-2])
                matched = prefix is not None and actual[: len(prefix)] == prefix
                continue
            operator = "=="
            for candidate in (">=", "<=", "~=", ">", "<", "==", "="):
                if clause.startswith(candidate):
                    operator = candidate
                    clause = clause[len(candidate) :].strip()
                    break
            if clause.endswith("+"):
                operator = ">="
                clause = clause[:-1]
            expected = parse(clause)
            if expected is None:
                matched = False
                continue
            relation = compare(actual, expected)
            if operator in {"=", "=="}:
                matched = relation == 0
            elif operator == ">=":
                matched = relation >= 0
            elif operator == "<=":
                matched = relation <= 0
            elif operator == ">":
                matched = relation > 0
            elif operator == "<":
                matched = relation < 0
            elif operator == "~=":
                matched = relation >= 0 and actual[:1] == expected[:1]
            if not matched:
                break
        if matched:
            return True
    return False


def build_plugin_selection_plan(
    project_path: str | Path,
    inventory: dict[str, Any],
    *,
    registry: PluginRegistry | None = None,
    explicit_framework_ids: set[str] | None = None,
) -> PluginSelectionPlan:
    registry = registry or discover_plugin_registry(project_path)
    plan = PluginSelectionPlan(registry=registry)
    explicit_framework_ids = explicit_framework_ids or set()
    for plugin in registry.language_plugins():
        manifest = plugin.manifest
        selected, reason = _language_selected(manifest, inventory)
        if selected:
            plan.selected_language_ids.append(manifest.id)
            plan.cache_keys[manifest.id] = manifest.cache_key
            plan.versions[manifest.id] = manifest.version
        else:
            plan.rejected.append({"id": manifest.id, "kind": "language", "version": manifest.version, "cache_key": manifest.cache_key, "reason": reason})
    for plugin in registry.framework_plugins():
        manifest = plugin.manifest
        selected, reason, evidence = _framework_selected(
            manifest, inventory, explicit_local=manifest.id in explicit_framework_ids
        )
        if selected:
            plan.selected_framework_ids.append(manifest.id)
            plan.cache_keys[manifest.id] = manifest.cache_key
            plan.versions[manifest.id] = manifest.version
            plan.diagnostics.append(PluginDiagnostic(manifest.id, "info", "plugin_activated", reason, {"evidence": evidence}))
        else:
            plan.rejected.append({"id": manifest.id, "kind": "framework", "version": manifest.version, "cache_key": manifest.cache_key, "reason": reason, "evidence": evidence})
            plan.diagnostics.append(PluginDiagnostic(manifest.id, "info", "plugin_rejected", reason, {}))
    return plan
