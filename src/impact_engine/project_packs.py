"""Project-local support packs for evidence-gated personalization.

These packs live beside the analyzed project instead of the CodeSlicer source
tree. They can teach one project about a custom wrapper, internal framework,
or private SDK while keeping the shared support-pack registry unchanged.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from impact_engine.support_packs.registry import list_local_support_packs, validate_support_pack_file
from impact_engine.support_packs.schema import (
    SUPPORT_PACK_INACTIVE_TRUST_LEVELS,
    SUPPORT_PACK_TRUST_LEVELS,
    SupportPack,
    is_support_pack_active,
    support_pack_from_dict,
    support_pack_to_dict,
    validate_support_pack_dict,
)


LOCAL_PACKS_RELATIVE_PATH = Path(".impact_engine") / "local_packs"
LOCAL_ALLOWED_TRUST_LEVELS = SUPPORT_PACK_TRUST_LEVELS - {"trusted"}
_STRONG_MATCH_KEYS = {
    "decorator",
    "imported_library",
    "receiver",
    "receiver_type",
    "parameter_type",
    "provider",
    "module",
    "file_pattern",
}
_RULES_REQUIRING_STRONG_MATCH = {
    "standard",
    "method_call_alias",
    "framework_route",
    "constructor_injection",
}


def project_pack_root(project_path: str | Path) -> Path:
    return Path(project_path).expanduser().resolve() / LOCAL_PACKS_RELATIVE_PATH


def initialize_project_packs(project_path: str | Path) -> dict[str, Any]:
    root = project_pack_root(project_path)
    root.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ok",
        "scope": "project_local",
        "root": str(root),
        "message": "Project-local support pack directory is ready.",
    }


def list_project_packs(project_path: str | Path) -> list[dict[str, Any]]:
    root = project_pack_root(project_path)
    result: list[dict[str, Any]] = []
    for path in list_local_support_packs(root):
        validation = validate_support_pack_file(path)
        data: dict[str, Any] | None = None
        if validation["valid"]:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                data = loaded if isinstance(loaded, dict) else None
                local_errors = validate_project_pack_dict(data or {})
                if local_errors:
                    validation = {**validation, "valid": False, "errors": local_errors}
            except (OSError, json.JSONDecodeError) as exc:
                validation = {**validation, "valid": False, "errors": [str(exc)]}
        row: dict[str, Any] = {
            "path": str(path),
            "valid": validation["valid"],
            "errors": validation.get("errors", []),
            "scope": "project_local",
        }
        if validation["valid"]:
            assert data is not None
            row.update({
                "library": data.get("library"),
                "language": data.get("language"),
                "trust_level": data.get("trust_level") or data.get("status"),
                "active": is_support_pack_active(data.get("status"), data.get("trust_level")),
                "project_scope": data.get("project_scope", {}),
            })
        result.append(row)
    return result


def load_project_packs(project_path: str | Path) -> tuple[list[SupportPack], list[str]]:
    """Load valid project-local packs and return validation errors separately."""
    packs: list[SupportPack] = []
    errors: list[str] = []
    for row in list_project_packs(project_path):
        if not row["valid"]:
            errors.append(f"Invalid project-local pack {row['path']}: {', '.join(row['errors'])}")
            continue
        try:
            data = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
            if data.get("scope") != "project_local":
                errors.append(f"Project-local pack {row['path']} has invalid scope")
                continue
            pack = support_pack_from_dict(data)
            packs.append(pack)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"Failed to load project-local pack {row['path']}: {exc}")
    return packs, errors


def install_project_pack(
    project_path: str | Path,
    pack_path: str | Path,
    *,
    trust_level: str = "draft",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Validate and install a candidate as a pack scoped to one project.

    The function never writes to ``support_packs/`` or the global SQLite
    registry. ``trusted`` is deliberately unavailable for local-only packs:
    global trust requires promotion through the shared validation workflow.
    """
    candidate_path = Path(pack_path).expanduser().resolve()
    if not candidate_path.is_file():
        return {"status": "error", "errors": [f"Pack file does not exist: {candidate_path}"]}
    if trust_level not in LOCAL_ALLOWED_TRUST_LEVELS:
        return {
            "status": "error",
            "errors": [
                "project-local packs may use draft, staged, experimental, "
                "verified_on_fixture, or verified_on_real_project trust levels"
            ],
        }
    try:
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "error", "errors": [str(exc)]}
    if not isinstance(candidate, dict):
        return {"status": "error", "errors": ["Support pack must be a JSON object"]}

    project = Path(project_path).expanduser().resolve()
    if not project.is_dir():
        return {"status": "error", "errors": [f"Project directory does not exist: {project}"]}

    candidate["scope"] = "project_local"
    candidate["project_scope"] = {
        "project_name": project.name,
        "storage": str(LOCAL_PACKS_RELATIVE_PATH).replace("\\", "/"),
        "candidate_source": str(candidate_path),
    }
    candidate["status"] = trust_level
    candidate["trust_level"] = trust_level

    errors = validate_project_pack_dict(candidate)
    if errors:
        return {"status": "error", "errors": errors}

    language = _safe_component(str(candidate["language"]).lower())
    library = _safe_component(str(candidate["library"]).lower())
    target = project_pack_root(project) / language / library / "support_pack.json"
    if target.exists() and not overwrite:
        return {
            "status": "already_exists",
            "path": str(target),
            "message": "Use --overwrite to replace this project-local pack.",
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "installed",
        "path": str(target),
        "scope": "project_local",
        "trust_level": trust_level,
        "active": trust_level not in SUPPORT_PACK_INACTIVE_TRUST_LEVELS,
        "message": "Installed only for this project; the shared registry was not changed.",
    }


def validate_project_pack_dict(pack: dict[str, Any]) -> list[str]:
    errors = list(validate_support_pack_dict(pack))
    if pack.get("scope") != "project_local":
        errors.append("project-local pack must declare scope=project_local")
    if pack.get("trust_level") == "trusted":
        errors.append("project-local pack cannot declare trusted; promote it to the shared registry instead")

    requirements = pack.get("evidence_requirements") or {}
    if not isinstance(requirements, dict) or requirements.get("forbid_name_only") is not True:
        errors.append("project-local pack must set evidence_requirements.forbid_name_only=true")

    for index, rule in enumerate(pack.get("edge_rules") or []):
        if not isinstance(rule, dict):
            continue
        rule_type = str(rule.get("type") or "standard")
        match = rule.get("match") or {}
        if rule_type in _RULES_REQUIRING_STRONG_MATCH and not any(key in match for key in _STRONG_MATCH_KEYS):
            errors.append(
                f"edge_rules[{index}] requires import, receiver, type, decorator, provider, module, or file evidence; name-only matching is forbidden"
            )
    return errors


def _safe_component(value: str) -> str:
    result = re.sub(r"[^a-z0-9._-]+", "-", value).strip(".-")
    if not result:
        raise ValueError("Support pack language and library must contain safe path characters")
    return result
