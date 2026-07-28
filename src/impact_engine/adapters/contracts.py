"""Contracts for optional, local-only CodeSlicer adapters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ADAPTER_MANIFEST_SCHEMA_VERSION = "CodeSlicerAdapterManifest/v1"
EVIDENCE_OVERLAY_SCHEMA_VERSION = "CodeSlicerEvidenceOverlay/v1"
VALID_EXECUTION = {"local-artifact", "local-process"}
VALID_EVIDENCE_CLASSES = {
    "STATIC_EXTRACTED", "SEMANTIC_INDEX", "CONTRACT_CONFIRMED",
    "RUNTIME_OBSERVED", "LSP_RUNTIME", "SECURITY_FINDING", "CPG_STATIC", "CPG_DATAFLOW", "DOC_INFERRED", "USER_ASSERTED",
}


def validate_manifest(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["manifest must be an object"]
    errors: list[str] = []
    required = {"id", "display_name", "version", "execution", "network_default", "inputs", "evidence_class", "resource_profile", "affects_review_ranking"}
    errors.extend(f"missing required field: {key}" for key in sorted(required - set(data)))
    if data.get("execution") not in VALID_EXECUTION:
        errors.append("execution must be local-artifact or local-process")
    if data.get("network_default") != "disabled":
        errors.append("network_default must be disabled")
    if not isinstance(data.get("inputs"), list) or not all(isinstance(item, str) for item in data.get("inputs", [])):
        errors.append("inputs must be a list of strings")
    if data.get("evidence_class") not in VALID_EVIDENCE_CLASSES:
        errors.append("evidence_class is not supported")
    if not isinstance(data.get("affects_review_ranking"), bool) or data.get("affects_review_ranking") is not False:
        errors.append("adapters cannot affect Review ranking")
    return errors


@dataclass(frozen=True)
class AdapterManifest:
    id: str
    display_name: str
    version: str
    execution: str
    network_default: str
    inputs: tuple[str, ...]
    evidence_class: str
    resource_profile: str
    affects_review_ranking: bool
    path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str | None = None) -> "AdapterManifest":
        errors = validate_manifest(data)
        if errors:
            raise ValueError("; ".join(errors))
        return cls(
            id=str(data["id"]), display_name=str(data["display_name"]), version=str(data["version"]),
            execution=str(data["execution"]), network_default=str(data["network_default"]),
            inputs=tuple(str(item) for item in data["inputs"]), evidence_class=str(data["evidence_class"]),
            resource_profile=str(data["resource_profile"]), affects_review_ranking=False, path=path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "display_name": self.display_name, "version": self.version,
            "execution": self.execution, "network_default": self.network_default,
            "inputs": list(self.inputs), "evidence_class": self.evidence_class,
            "resource_profile": self.resource_profile, "affects_review_ranking": False,
            "manifest_path": self.path,
        }


def normalize_overlay(
    *, adapter_id: str, adapter_version: str, source_kind: str, evidence_class: str,
    confidence: str, freshness: dict[str, Any], local_artifact_reference: dict[str, Any],
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], diagnostics: list[dict[str, Any]],
    enabled: bool, availability: str = "ready", error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_OVERLAY_SCHEMA_VERSION,
        "adapter_id": adapter_id, "adapter_version": adapter_version,
        "source_kind": source_kind, "evidence_class": evidence_class,
        "confidence": confidence, "freshness": freshness,
        "local_artifact_reference": local_artifact_reference,
        "source": {"adapter_id": adapter_id, "source_kind": source_kind, "local_artifact_reference": local_artifact_reference},
        "nodes": nodes, "edges": edges, "diagnostics": diagnostics,
        "privacy": {"mode": "local-only", "network_used": False},
        "network_used": False, "enabled": enabled, "availability": availability,
        "error": error,
    }
