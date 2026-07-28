"""Versioned, local-first contracts shared by CodeSlicer product modes.

The legacy review payload is intentionally preserved.  New fields are added
through this module so CLI, local API and MCP do not each invent a slightly
different envelope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


MODE_CONTRACT_VERSION = "CodeSlicerModeContract/v2"
MODE_SCHEMA_VERSION = "CodeSlicerModeReport/v1"
MODE_RESPONSE_SCHEMA_VERSION = "CodeSlicerModeContract/v2"
CI_POLICY_SCHEMA_VERSION = "CodeSlicerCIPolicy/v1"
SARIF_VERSION = "2.1.0"

ACTION_KINDS = (
    "inspect_entity",
    "investigate_entity",
    "explain_edge",
    "run_recommended_test",
    "open_file",
    "refresh_graph",
    "view_coverage",
    "acknowledge_warning",
)


@dataclass(frozen=True)
class ModeAction:
    id: str
    kind: str
    title: str
    enabled: bool = True
    requires_explicit_user_action: bool = True
    payload: dict[str, Any] = field(default_factory=dict)
    reason_disabled: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ACTION_KINDS:
            raise ValueError(f"Unsupported CodeSlicer action kind: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "enabled": self.enabled,
            "requires_explicit_user_action": self.requires_explicit_user_action,
            "payload": dict(self.payload),
        }
        if self.reason_disabled:
            result["reason_disabled"] = self.reason_disabled
        return result


def action(
    action_id: str,
    kind: str,
    title: str,
    *,
    payload: dict[str, Any] | None = None,
    enabled: bool = True,
    requires_explicit_user_action: bool = True,
    reason_disabled: str | None = None,
) -> dict[str, Any]:
    """Serialize one action and validate its kind in one place."""

    return ModeAction(
        id=action_id,
        kind=kind,
        title=title,
        payload=payload or {},
        enabled=enabled,
        requires_explicit_user_action=requires_explicit_user_action,
        reason_disabled=reason_disabled,
    ).to_dict()


def action_bundle(items: Iterable[dict[str, Any]], **legacy: Any) -> dict[str, Any]:
    """Return structured actions while retaining legacy review action keys."""

    return {"items": list(items), **legacy}


def contract_metadata(mode: str, *, schema_version: str = MODE_SCHEMA_VERSION) -> dict[str, Any]:
    return {
        "contract_version": MODE_CONTRACT_VERSION,
        "legacy_contract_version": "CodeSlicerModeContract/v1",
        "schema_version": schema_version,
        "mode": mode,
        "local_only": True,
        "privacy": {
            "mode": "local-only",
            "network_used": False,
            "source_upload": False,
            "graph_upload": False,
            "telemetry": False,
            "network_by_default": False,
        },
    }


def attach_mode_contract(
    payload: dict[str, Any],
    mode: str,
    *,
    schema_version: str = MODE_SCHEMA_VERSION,
    actions: Iterable[dict[str, Any]] | None = None,
    legacy_actions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add the common envelope without removing any existing payload fields."""

    payload.update(contract_metadata(mode, schema_version=schema_version))
    payload["mode_contract"] = {
        "name": "codeslicer-modes",
        "version": MODE_CONTRACT_VERSION,
        "graph_document": "GraphDocument",
        "evidence_model": "Evidence + provenance + confidence",
        "coverage_model": "language/support coverage with explicit limitations",
        "actions": "CodeSlicerAction/v1",
    }
    payload.setdefault("graph_freshness", {"status": "unknown", "stale": True})
    payload.setdefault("freshness", payload.get("graph_freshness"))
    payload.setdefault("adapters", [])
    if isinstance(payload.get("graph_freshness"), dict):
        freshness = payload["graph_freshness"]
        freshness.setdefault("status", "stale" if freshness.get("stale") else "fresh")
    payload.setdefault("coverage", [])
    payload.setdefault("warnings", [])
    if actions is not None:
        payload["actions"] = action_bundle(actions, **(legacy_actions or {}))
    else:
        existing = payload.get("actions")
        if isinstance(existing, dict):
            existing.setdefault("items", [])
        else:
            payload["actions"] = action_bundle([], **(legacy_actions or {}))
    return payload


def _freshness_status(freshness: dict[str, Any] | None) -> str:
    value = dict(freshness or {})
    explicit = str(value.get("status") or "").lower()
    if explicit in {"fresh", "stale", "missing", "unknown"}:
        return explicit
    if explicit == "externally_supplied_unverified" or value.get("stale"):
        return "stale"
    if not value:
        return "unknown"
    return "fresh"


def _coverage_summary(coverage: Any) -> dict[str, Any]:
    """Normalize legacy coverage lists without losing their detailed items."""

    if isinstance(coverage, dict):
        items = list(coverage.get("items") or coverage.get("languages") or [])
        summary = dict(coverage)
    elif isinstance(coverage, list):
        items = list(coverage)
        summary = {}
    else:
        items = []
        summary = {}
    statuses = [str(item.get("status")) for item in items if isinstance(item, dict)]
    summary.setdefault("items", items)
    summary.setdefault("status", "unsupported" if any(item == "unsupported" for item in statuses) else ("partial" if any(item == "limited" for item in statuses) else "complete" if items else "unknown"))
    summary.setdefault("supported", sum(item == "supported" for item in statuses))
    summary.setdefault("partial", sum(item == "limited" for item in statuses))
    summary.setdefault("unsupported", sum(item == "unsupported" for item in statuses))
    return summary


def build_mode_response(
    mode: str,
    *,
    project: str | dict[str, Any] | None,
    freshness: dict[str, Any] | None,
    coverage: Any,
    warnings: Iterable[Any] = (),
    result: dict[str, Any] | None = None,
    adapters: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Return the public v2 localhost contract.

    The mode builders keep their historical flat payloads for CLI/MCP callers.
    Local API serializers use this envelope and put the historical payload in
    ``result`` so existing consumers can migrate without a second analyzer.
    """

    freshness_value = dict(freshness or {})
    if str(freshness_value.get("status") or "").lower() not in {"fresh", "stale", "missing", "unknown"}:
        freshness_value["status"] = _freshness_status(freshness_value)
    if isinstance(project, dict):
        project_value = dict(project)
    else:
        project_path = str(project or "")
        project_value = {
            "path": project_path,
            "name": project_path.rstrip("\\/").replace("\\", "/").rsplit("/", 1)[-1] if project_path else None,
        }
    warning_values = sorted({str(item) for item in warnings if item is not None})
    return {
        "schema_version": MODE_RESPONSE_SCHEMA_VERSION,
        "mode": mode,
        "project": project_value,
        "freshness": freshness_value,
        "coverage": _coverage_summary(coverage),
        "adapters": [dict(item) for item in adapters],
        "privacy": {"mode": "local-only", "network_used": False},
        "warnings": warning_values,
        "result": dict(result or {}),
    }


def mode_status(*, stale: bool = False, incomplete: bool = False) -> str:
    if stale:
        return "stale"
    if incomplete:
        return "incomplete"
    return "ok"
