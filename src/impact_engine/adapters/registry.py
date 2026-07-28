"""Generic discovery and project-local lifecycle for optional adapters."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from impact_engine.persistence import git_context
from impact_engine.project_storage import ensure_project_storage

from .contracts import AdapterManifest, validate_manifest
from .boundary import build_boundary_overlay, parse_boundary_spec
from .graphify import build_graphify_overlay
from .codegraph import build_codegraph_overlay
from .gortex import build_gortex_overlay
from .lsp import load_lsp_overlay, lsp_status
from .otel import build_otel_overlay, parse_otel_document, parse_otel_trace
from .scip import build_scip_overlay, parse_scip_artifact
from .security import build_security_overlay, parse_security_report
from .joern import build_joern_overlay, calibrate_joern_overlay, parse_joern_artifact
from .native import native_profile
from impact_engine.tool_runtime import ToolRuntime


MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdapterRegistry:
    """Registry/lifecycle boundary; adapters never mutate the canonical graph."""

    def __init__(self, project_path: str | Path, repository_root: str | Path | None = None) -> None:
        self.project_path = Path(project_path).expanduser().resolve()
        self.repository_root = Path(repository_root).resolve() if repository_root else Path(__file__).resolve().parents[3]
        self.storage = ensure_project_storage(self.project_path)
        self.adapter_state_dir = self.storage / "adapters"

    def _adapter_ids(self) -> list[str]:
        root = self.repository_root / "plugins" / "adapters"
        if not root.is_dir():
            return []
        discovered = sorted(path.parent.name for path in root.glob("*/plugin.json"))
        # Keep the historical Graphify-first ordering for existing CLI/UI
        # consumers while allowing every discovered adapter to participate.
        historical_order = ["graphify", "asyncapi", "lsp", "openapi", "otel", "scip", "codegraph", "joern", "gortex"]
        ordered = [item for item in historical_order if item in discovered]
        return ordered + [item for item in discovered if item not in ordered]

    def _manifest(self, adapter_id: str) -> tuple[AdapterManifest | None, list[str]]:
        path = self.repository_root / "plugins" / "adapters" / adapter_id / "plugin.json"
        if not path.is_file():
            return None, [f"adapter manifest not found: {adapter_id}"]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            errors = validate_manifest(data)
            return (AdapterManifest.from_dict(data, str(path)) if not errors else None), errors
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return None, [str(exc)]

    def _state_path(self, adapter_id: str) -> Path:
        return self.adapter_state_dir / f"{adapter_id}.json"

    def _state(self, adapter_id: str) -> dict[str, Any]:
        path = self._state_path(adapter_id)
        if not path.is_file():
            return {"enabled": False}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"enabled": False}
        except (OSError, ValueError, json.JSONDecodeError):
            return {"enabled": False, "status": "error", "diagnostics": ["invalid project-local adapter state"]}

    def _write_state(self, adapter_id: str, data: dict[str, Any]) -> None:
        self._state_path(adapter_id).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _freshness(self, state: dict[str, Any]) -> dict[str, Any]:
        artifact = Path(str(state.get("artifact_path") or ""))
        if not artifact.is_file():
            return {"status": "missing", "verified": False}
        try:
            expected = str(state.get("artifact_fingerprint") or "")
            if expected and _sha256(artifact) != expected:
                return {"status": "stale", "verified": False, "reason": "artifact fingerprint changed"}
            source = Path(str(state.get("source_path") or ""))
            source_fp = str(state.get("source_fingerprint") or "")
            if source_fp:
                if not source.is_file():
                    return {"status": "unverified", "verified": False, "reason": "source artifact is unavailable"}
                if _sha256(source) != source_fp:
                    return {"status": "stale", "verified": False, "reason": "source artifact fingerprint changed"}
            current_head = git_context(self.project_path).get("head")
            artifact_project = state.get("artifact_project_path")
            if artifact_project:
                if not Path(str(artifact_project)).is_absolute():
                    return {"status": "unverified", "verified": False, "reason": "artifact project path is not absolute"}
                if Path(str(artifact_project)).resolve() != self.project_path:
                    return {"status": "stale", "verified": False, "reason": "artifact project path differs from selected project"}
            artifact_head = state.get("artifact_project_head")
            if artifact_head and not current_head:
                return {"status": "unverified", "verified": False, "reason": "Joern project HEAD is unavailable for artifact verification"}
            if artifact_head and current_head and artifact_head != current_head:
                return {"status": "stale", "verified": False, "reason": "Joern project commit differs from selected project HEAD"}
            recorded_head = state.get("project_head")
            if recorded_head and not current_head:
                return {"status": "unverified", "verified": False, "reason": "project Git HEAD is unavailable"}
            if recorded_head and current_head and recorded_head != current_head:
                return {"status": "stale", "verified": False, "reason": "project Git HEAD changed"}
            index_commit = state.get("semantic_index_commit")
            if index_commit and not current_head:
                return {"status": "unverified", "verified": False, "reason": "project Git HEAD is unavailable for semantic index verification"}
            if index_commit and current_head and index_commit != current_head:
                return {"status": "stale", "verified": False, "reason": "semantic index commit differs from project HEAD"}
            if not state.get("project_path") or Path(str(state["project_path"])).resolve() != self.project_path:
                return {"status": "stale", "verified": False, "reason": "artifact belongs to another project"}
            indexed_root = str(state.get("semantic_index_project_root") or "")
            if indexed_root:
                parsed_root = urlparse(indexed_root)
                if parsed_root.scheme.lower() != "file" or parsed_root.netloc not in {"", "localhost"}:
                    return {"status": "unverified", "verified": False, "reason": "SCIP project_root is not a local file URI"}
                indexed_path = Path(url2pathname(unquote(parsed_root.path))).expanduser()
                if not indexed_path.is_absolute() or not indexed_path.exists():
                    return {"status": "unverified", "verified": False, "reason": "SCIP file URI project_root cannot be verified locally"}
                if indexed_path.resolve() != self.project_path:
                    return {"status": "stale", "verified": False, "reason": "SCIP project_root differs from selected project"}
            return {"status": "fresh", "verified": True, "created_at": state.get("created_at")}
        except (OSError, ValueError):
            return {"status": "unverified", "verified": False}

    def status(self, adapter_id: str = "graphify") -> dict[str, Any]:
        manifest, errors = self._manifest(adapter_id)
        if adapter_id == "lsp":
            status = lsp_status(self.project_path)
            status["manifest"] = manifest.to_dict() if manifest else None
            status["native"] = native_profile(adapter_id, self._state(adapter_id).get("native_executable"))
            status["tool_runtime"] = ToolRuntime(self.project_path).status(adapter_id)
            if errors:
                status["status"] = "unavailable"
                status["diagnostics"] = list(status.get("diagnostics") or []) + errors
            return status
        state = self._state(adapter_id)
        freshness = self._freshness(state) if state.get("artifact_path") else {"status": "unknown", "verified": False}
        diagnostics = list(errors) + list(state.get("diagnostics") or [])
        enabled = bool(state.get("enabled", False))
        if state.get("status") in {"error", "unsupported", "incomplete"}:
            status = str(state.get("status"))
            if status == "error":
                diagnostics.append("invalid project-local adapter state")
        elif errors:
            status = "unavailable"
        elif not enabled:
            status = freshness.get("status") if state.get("artifact_path") and freshness.get("status") in {"stale", "unverified"} else ("imported" if state.get("artifact_path") and freshness.get("status") == "fresh" else "disabled")
        elif not state.get("artifact_path"):
            status = "unavailable"
            diagnostics.append(f"Import a local {adapter_id} artifact to enable the adapter")
        elif freshness["status"] in {"stale", "unverified"}:
            status = freshness["status"]
        else:
            status = "ready"
        return {
            "id": adapter_id, "status": status, "enabled": enabled,
            "source": "local-artifact", "freshness": freshness,
            "network_used": False, "diagnostics": diagnostics,
            "format": state.get("format"), "traces": state.get("traces", 0),
            "spans": state.get("spans", 0), "services": state.get("services", 0),
            "depth": state.get("depth", 0),
            "paths": state.get("paths", (state.get("summary") or {}).get("paths", 0)),
            "components": (state.get("summary") or {}).get("components", 0),
            "findings": (state.get("summary") or {}).get("findings", 0),
            "licenses": (state.get("summary") or {}).get("licenses", 0),
            "severity": (state.get("summary") or {}).get("severity", {}),
            "artifact": {key: state.get(key) for key in (
                "artifact_path", "source_path", "artifact_fingerprint", "created_at",
                "nodes", "edges", "semantic_index_commit", "semantic_index_version",
                "semantic_index_project_root", "semantic_index_created_at", "semantic_index_format",
                "spec_format", "spec_version", "summary",
                "format", "traces", "spans", "services", "depth", "tool", "timestamp",
                "source_path", "source_fingerprint", "paths", "artifact_project_path", "artifact_project_head",
            ) if state.get(key) is not None},
            "live_receiver": self.otel_live_receiver() if adapter_id == "otel" else None,
            "manifest": manifest.to_dict() if manifest else None,
            "native": native_profile(adapter_id, state.get("native_executable")),
            "tool_runtime": ToolRuntime(self.project_path).status(adapter_id),
        }

    def list(self) -> list[dict[str, Any]]:
        return [self.status(adapter_id) for adapter_id in self._adapter_ids()]

    def configure_native_executable(self, adapter_id: str, executable: str | Path | None) -> dict[str, Any]:
        """Persist one explicit local tool path, never a shell command.

        The path is project-local (`.codeslicer/adapters`) so a user can keep
        an isolated tool install, a .bat launcher, or a WSL wrapper without
        changing PATH for the rest of the machine.
        """
        if native_profile(adapter_id).get("mode") != "native-local-tool":
            raise ValueError(f"{adapter_id} is an artifact/protocol source and has no native executable setting")
        if executable is None or not str(executable).strip():
            state = self._state(adapter_id)
            state.pop("native_executable", None)
            self._write_state(adapter_id, state)
            return self.status(adapter_id)
        candidate = Path(str(executable)).expanduser()
        if not candidate.is_absolute() or not candidate.is_file():
            raise ValueError("native executable must be an existing absolute local file")
        state = self._state(adapter_id)
        state.update({"native_executable": str(candidate.resolve()), "updated_at": _now()})
        self._write_state(adapter_id, state)
        return self.status(adapter_id)

    def preflight(self, adapter_id: str | None = None) -> dict[str, Any]:
        """Describe the explicit local action required for every adapter.

        This intentionally performs no discovery outside the selected project
        and never starts a subprocess.  It is safe to call from a CLI, IDE or
        CI to render one consistent "connect optional evidence" experience.
        """
        adapter_ids = [adapter_id] if adapter_id else self._adapter_ids()
        items: list[dict[str, Any]] = []
        for current_id in adapter_ids:
            manifest, errors = self._manifest(current_id)
            if manifest is None:
                items.append({"id": current_id, "status": "unavailable", "diagnostics": errors})
                continue
            status = self.status(current_id)
            state = self._state(current_id)
            if current_id == "lsp":
                configured = bool(state.get("executable") and state.get("workspace_roots"))
                next_action = (
                    "probe" if configured else "configure"
                )
                command = (
                    f"impact-engine adapters lsp probe {self.project_path}"
                    if configured else
                    f"impact-engine adapters lsp configure {self.project_path} --executable <absolute-local-lsp> --workspace-root {self.project_path}"
                )
            elif status["status"] == "ready":
                next_action = "inspect"
                command = f"impact-engine adapters status {self.project_path} {current_id}"
            elif state.get("artifact_path"):
                next_action = "enable" if status["status"] == "imported" else "refresh_artifact"
                command = (
                    f"impact-engine adapters enable {self.project_path} {current_id}"
                    if next_action == "enable" else
                    f"impact-engine adapters import {self.project_path} {current_id} <absolute-local-artifact> --enable"
                )
            else:
                next_action = "import"
                command = f"impact-engine adapters import {self.project_path} {current_id} <absolute-local-artifact> --enable"
            items.append({
                "id": current_id,
                "display_name": manifest.display_name,
                "execution": manifest.execution,
                "resource_profile": manifest.resource_profile,
                "inputs": list(manifest.inputs),
                "evidence_class": manifest.evidence_class,
                "affects_review_ranking": False,
                "status": status["status"],
                "enabled": bool(status["enabled"]),
                "next_action": next_action,
                "command": command,
                "diagnostics": list(status.get("diagnostics") or []),
                "privacy": {"mode": "local-only", "network_used": False},
                "native": native_profile(current_id, state.get("native_executable")),
            })
        return {
            "status": "ok",
            "project_path": str(self.project_path),
            "adapters": items,
            "privacy": {"mode": "local-only", "network_used": False},
        }

    def set_enabled(self, adapter_id: str, enabled: bool) -> dict[str, Any]:
        if adapter_id == "lsp":
            from .lsp import disable_lsp
            if not enabled:
                return disable_lsp(self.project_path)
            state = self._state(adapter_id)
            if not state.get("executable") or not state.get("workspace_roots"):
                raise ValueError("LSP must be configured with an executable and workspace roots before enabling")
            state.update({"enabled": True, "updated_at": _now()})
            self._write_state(adapter_id, state)
            return self.status(adapter_id)
        manifest, errors = self._manifest(adapter_id)
        if errors or manifest is None:
            raise ValueError("; ".join(errors))
        state = self._state(adapter_id)
        if enabled:
            if not state.get("artifact_path"):
                raise ValueError(
                    f"{adapter_id} cannot be enabled without an explicit local artifact; "
                    f"run: impact-engine adapters import {self.project_path} {adapter_id} <absolute-local-artifact> --enable"
                )
            freshness = self._freshness(state)
            if freshness.get("status") != "fresh":
                raise ValueError(f"{adapter_id} artifact is not fresh: {freshness.get('reason') or freshness.get('status')}")
            if state.get("status") in {"error", "unsupported", "incomplete"}:
                raise ValueError(f"{adapter_id} artifact is not ready: {state.get('status')}")
        state.update({"enabled": enabled, "updated_at": _now()})
        self._write_state(adapter_id, state)
        return self.status(adapter_id)

    def import_artifact(self, adapter_id: str, source_path: str | Path) -> dict[str, Any]:
        manifest, errors = self._manifest(adapter_id)
        if errors or manifest is None:
            raise ValueError("; ".join(errors))
        source = Path(source_path).expanduser()
        if not source.is_absolute():
            raise ValueError("artifact_path must be an absolute local path")
        if not source.is_file():
            raise FileNotFoundError(f"{adapter_id} artifact does not exist: {source}")
        if source.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError(f"{adapter_id} artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
        if adapter_id == "graphify":
            try:
                data = json.loads(source.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("nodes", []), list):
                    raise ValueError("Graphify artifact must be a JSON object with a nodes array")
                overlay = build_graphify_overlay(data, artifact_path=str(source), project_root=self.project_path)
            except UnicodeDecodeError as exc:
                raise ValueError("Graphify artifact must be UTF-8 JSON") from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid Graphify JSON: {exc.msg}") from exc
            target_name = "graph.json"
        elif adapter_id == "codegraph":
            try:
                data = json.loads(source.read_text(encoding="utf-8"))
            except UnicodeDecodeError as exc:
                raise ValueError("CodeGraph artifact must be UTF-8 JSON") from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid CodeGraph JSON: {exc.msg}") from exc
            overlay = build_codegraph_overlay(data, artifact_path=str(source), project_root=self.project_path)
            target_name = "graph.json"
        elif adapter_id == "gortex":
            if source.suffix.lower() not in {".graphml", ".json"}:
                raise ValueError("gortex import accepts only a local .graphml export or .json query result created by Gortex")
            overlay = build_gortex_overlay(source, project_root=self.project_path)
            target_name = "graph.json"
        elif adapter_id == "scip":
            try:
                data = parse_scip_artifact(source)
                overlay = build_scip_overlay(data, artifact_path=str(source), project_root=self.project_path)
            except UnicodeDecodeError as exc:
                raise ValueError("SCIP artifact is neither valid UTF-8 JSON interchange nor binary protobuf") from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid SCIP JSON interchange: {exc.msg}") from exc
            target_name = "index.scip"
        elif adapter_id in {"openapi", "asyncapi"}:
            if source.suffix.lower() not in {".json", ".yaml", ".yml"}:
                raise ValueError(f"{adapter_id} import accepts only local .json, .yaml, or .yml files")
            parsed = parse_boundary_spec(source, adapter_id)
            overlay = build_boundary_overlay(
                parsed,
                adapter_id,
                artifact_path=str(source),
                source_spec_path=str(source.resolve()),
                project_root=self.project_path,
            )
            target_name = f"spec{source.suffix.lower()}"
        elif adapter_id == "otel":
            parsed = parse_otel_trace(source)
            overlay = build_otel_overlay(parsed, artifact_path=str(source), project_root=self.project_path)
            target_name = "trace.json"
        elif adapter_id == "joern":
            parsed = parse_joern_artifact(source)
            overlay = build_joern_overlay(parsed, artifact_path=str(source), project_root=self.project_path)
            target_name = "overlay.json"
        elif adapter_id in {"cyclonedx", "spdx", "sarif"}:
            allowed_suffixes = {".json", ".sarif"} if adapter_id == "sarif" else {".json"}
            if source.suffix.lower() not in allowed_suffixes:
                accepted = ".json or .sarif" if adapter_id == "sarif" else ".json"
                raise ValueError(f"{adapter_id} import accepts only a local {accepted} report")
            parsed = parse_security_report(source, adapter_id)
            overlay = build_security_overlay(parsed, artifact_path=str(source), adapter_id=adapter_id, project_root=self.project_path)
            target_name = "report.json"
        else:
            raise ValueError(f"No importer is registered for adapter: {adapter_id}")
        target = self.storage / "artifacts" / adapter_id / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if adapter_id in {"graphify", "codegraph", "gortex", "cyclonedx", "spdx", "sarif", "joern", "otel"}:
            # Keep only the normalized overlay in .codeslicer; the user-owned
            # source remains at its original local path. This also prevents
            # external graph artifacts from becoming an accidental raw cache.
            overlay["local_artifact_reference"] = {"path": str(target.resolve())}
            target.write_text(json.dumps(overlay, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            shutil.copyfile(source, target)
        state = self._state(adapter_id)
        index_metadata = overlay.get("index_metadata", {}) if isinstance(overlay, dict) else {}
        joern_metadata = overlay.get("metadata") if adapter_id == "joern" and isinstance(overlay.get("metadata"), dict) else {}
        state.update({
            "artifact_path": str(target), "source_path": str(source.resolve()),
            "artifact_fingerprint": _sha256(target), "source_fingerprint": _sha256(source),
            "created_at": _now(), "project_path": str(self.project_path),
            "project_head": git_context(self.project_path).get("head"),
            "artifact_project_path": overlay.get("project_path") if adapter_id == "joern" else None,
            "artifact_project_head": joern_metadata.get("commit") if adapter_id == "joern" else None,
            "nodes": len(overlay.get("nodes", [])), "edges": len(overlay.get("edges", [])),
            "diagnostics": overlay.get("diagnostics", []),
            "semantic_index_commit": index_metadata.get("commit"),
            "semantic_index_version": index_metadata.get("version") or index_metadata.get("tool_version"),
            "semantic_index_project_root": index_metadata.get("project_root"),
            "semantic_index_created_at": index_metadata.get("created_at"),
            "semantic_index_format": overlay.get("index_metadata", {}).get("format"),
            "spec_format": overlay.get("spec_format"),
            "spec_version": overlay.get("spec_version"),
            "summary": overlay.get("summary", {}),
            "tool": overlay.get("tool", {}),
            "timestamp": overlay.get("timestamp"),
            "paths": (overlay.get("summary") or {}).get("paths", 0),
            "format": overlay.get("format"),
            "traces": overlay.get("summary", {}).get("traces", 0),
            "spans": overlay.get("summary", {}).get("spans", 0),
            "services": overlay.get("summary", {}).get("services", 0),
            "depth": max((int(node.get("properties", {}).get("depth", 0)) for node in overlay.get("nodes", []) if isinstance(node, dict)), default=0),
            "status": (
                overlay.get("availability") if overlay.get("availability") in {"unsupported", "incomplete"}
                else "error" if any(item.get("severity") == "error" for item in overlay.get("diagnostics", []) if isinstance(item, dict))
                else state.get("status")
            ),
        })
        self._write_state(adapter_id, state)
        overlay["local_artifact_reference"] = {"path": str(target.resolve()), "fingerprint": state["artifact_fingerprint"]}
        return {"status": "imported", "adapter": self.status(adapter_id), "overlay": overlay}

    def import_otel_document(self, document: dict[str, Any], *, source_label: str = "otlp-http-json") -> dict[str, Any]:
        """Store a *sanitized* OTLP JSON observation from the loopback receiver.

        The HTTP receiver calls this method only after a user enables capture.
        The original request body is deliberately never written to disk: the
        persisted artifact is the same allowlisted evidence overlay exposed to
        the rest of CodeSlicer.
        """
        if not isinstance(document, dict):
            raise ValueError("OTLP JSON payload must be an object")
        parsed = parse_otel_document(document)
        overlay = build_otel_overlay(
            parsed,
            artifact_path=source_label,
            project_root=self.project_path,
            freshness={"status": "fresh", "verified": True, "source": "loopback-live"},
            enabled=True,
        )
        target = self.storage / "artifacts" / "otel" / "trace.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        overlay["source"] = {
            **(overlay.get("source") or {}),
            "source_kind": "otlp-http-json-loopback",
            "source_artifact_path": source_label,
            "raw_payload_stored": False,
        }
        overlay["local_artifact_reference"] = {"path": str(target.resolve())}
        target.write_text(json.dumps(overlay, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        state = self._state("otel")
        state.update({
            "artifact_path": str(target), "artifact_fingerprint": _sha256(target),
            "source_path": None, "source_fingerprint": None,
            "created_at": _now(), "project_path": str(self.project_path),
            "project_head": git_context(self.project_path).get("head"),
            "enabled": True, "live_receiver": True,
            "diagnostics": overlay.get("diagnostics", []), "format": overlay.get("format"),
            "traces": overlay.get("summary", {}).get("traces", 0),
            "spans": overlay.get("summary", {}).get("spans", 0),
            "services": overlay.get("summary", {}).get("services", 0),
        })
        self._write_state("otel", state)
        return {"status": "imported", "adapter": self.status("otel"), "overlay": overlay}

    def set_otel_live_receiver(self, enabled: bool, *, endpoint: str) -> dict[str, Any]:
        """Opt in/out of the built-in loopback OTLP JSON receiver."""
        state = self._state("otel")
        state.update({"live_receiver_enabled": bool(enabled), "live_endpoint": endpoint, "updated_at": _now(), "project_path": str(self.project_path)})
        self._write_state("otel", state)
        return self.status("otel")

    def otel_live_receiver(self) -> dict[str, Any]:
        state = self._state("otel")
        return {
            "enabled": bool(state.get("live_receiver_enabled")),
            "endpoint": state.get("live_endpoint"),
            "persisted_raw_payload": False,
        }

    def import_graphify(self, source_path: str | Path) -> dict[str, Any]:
        """Backward-compatible Graphify-specific alias."""
        return self.import_artifact("graphify", source_path)

    def overlay(self, adapter_id: str = "graphify") -> dict[str, Any] | None:
        if adapter_id == "lsp":
            return load_lsp_overlay(self.project_path)
        state = self._state(adapter_id)
        if not state.get("enabled") or not state.get("artifact_path"):
            return None
        artifact = Path(str(state["artifact_path"]))
        if not artifact.is_file():
            return None
        freshness = self._freshness(state)
        if adapter_id == "graphify":
            try:
                stored = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                stored = None
            if isinstance(stored, dict) and stored.get("schema_version") == "CodeSlicerEvidenceOverlay/v1":
                stored["freshness"] = freshness
                stored["enabled"] = True
                stored["local_artifact_reference"] = {"path": str(artifact.resolve()), "fingerprint": state.get("artifact_fingerprint")}
                stored["source"] = {**(stored.get("source") or {}), "source_path": state.get("source_path"), "source_fingerprint": state.get("source_fingerprint")}
                if stored.get("availability") == "disabled":
                    stored["availability"] = "ready"
                return stored
            data = json.loads(artifact.read_text(encoding="utf-8"))
            return build_graphify_overlay(data, artifact_path=str(state.get("source_path") or artifact), project_root=self.project_path, freshness=freshness, enabled=True)
        if adapter_id == "codegraph":
            try:
                stored = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                stored = None
            if isinstance(stored, dict) and stored.get("schema_version") == "CodeSlicerEvidenceOverlay/v1":
                stored["freshness"] = freshness
                stored["enabled"] = True
                stored["local_artifact_reference"] = {"path": str(artifact.resolve()), "fingerprint": state.get("artifact_fingerprint")}
                stored["source"] = {**(stored.get("source") or {}), "source_path": state.get("source_path"), "source_fingerprint": state.get("source_fingerprint")}
                if stored.get("availability") == "disabled":
                    stored["availability"] = "ready"
                return stored
            data = json.loads(artifact.read_text(encoding="utf-8"))
            return build_codegraph_overlay(data, artifact_path=str(state.get("source_path") or artifact), project_root=self.project_path, freshness=freshness, enabled=True)
        if adapter_id == "gortex":
            try:
                stored = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                stored = None
            if isinstance(stored, dict) and stored.get("schema_version") == "CodeSlicerEvidenceOverlay/v1":
                stored["freshness"] = freshness
                stored["enabled"] = True
                stored["local_artifact_reference"] = {"path": str(artifact.resolve()), "fingerprint": state.get("artifact_fingerprint")}
                stored["source"] = {**(stored.get("source") or {}), "source_path": state.get("source_path"), "source_fingerprint": state.get("source_fingerprint")}
                if stored.get("availability") == "disabled":
                    stored["availability"] = "ready"
                return stored
            return build_gortex_overlay(state.get("source_path") or artifact, project_root=self.project_path, freshness=freshness, enabled=True)
        if adapter_id == "scip":
            data = parse_scip_artifact(artifact)
            return build_scip_overlay(data, artifact_path=str(artifact), project_root=self.project_path, freshness=freshness, enabled=True)
        if adapter_id in {"openapi", "asyncapi"}:
            parsed = parse_boundary_spec(artifact, adapter_id)
            return build_boundary_overlay(
                parsed,
                adapter_id,
                artifact_path=str(artifact),
                source_spec_path=str(state.get("source_path") or artifact),
                project_root=self.project_path,
                freshness=freshness,
                enabled=True,
            )
        if adapter_id == "otel":
            try:
                stored = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                stored = None
            if isinstance(stored, dict) and stored.get("schema_version") == "CodeSlicerRuntimeEvidenceOverlay/v1":
                stored["freshness"] = freshness
                stored["enabled"] = True
                stored["local_artifact_reference"] = {"path": str(artifact.resolve()), "fingerprint": state.get("artifact_fingerprint")}
                return stored
            parsed = parse_otel_trace(artifact)
            return build_otel_overlay(
                parsed,
                artifact_path=str(artifact),
                project_root=self.project_path,
                freshness=freshness,
                enabled=True,
            )
        if adapter_id == "joern":
            try:
                stored = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return None
            if not isinstance(stored, dict) or stored.get("schema_version") != "CodeSlicerJoernEvidenceOverlay/v1":
                return None
            stored["freshness"] = freshness
            stored["enabled"] = True
            stored["overlay_only"] = True
            stored["participates_in_ranking"] = False
            stored["local_artifact_reference"] = {"path": str(artifact.resolve()), "fingerprint": state.get("artifact_fingerprint")}
            stored["source"] = {**(stored.get("source") or {}), "source_artifact_path": state.get("source_path"), "fingerprint": state.get("source_fingerprint")}
            return calibrate_joern_overlay(stored, freshness)
        if adapter_id in {"cyclonedx", "spdx", "sarif"}:
            try:
                stored = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                stored = None
            if isinstance(stored, dict) and stored.get("schema_version") == "CodeSlicerSecurityEvidenceOverlay/v1":
                stored["freshness"] = freshness
                stored["enabled"] = True
                return stored
            # Migrate artifacts created by the earlier raw-copy behavior to a
            # sanitized overlay before exposing them again.
            parsed = parse_security_report(artifact, adapter_id)
            sanitized = build_security_overlay(
                parsed,
                artifact_path=str(state.get("source_path") or artifact),
                adapter_id=adapter_id,
                project_root=self.project_path,
                freshness=freshness,
                enabled=True,
            )
            sanitized["local_artifact_reference"] = {"path": str(artifact.resolve())}
            artifact.write_text(json.dumps(sanitized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return sanitized
        raise ValueError(f"No overlay reader is registered for adapter: {adapter_id}")
