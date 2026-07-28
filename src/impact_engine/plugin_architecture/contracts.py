"""Typed, language-neutral contracts for CodeSlicer plugins.

Plugins receive facts and return graph contributions. They do not receive
network clients, arbitrary filesystem writers, or the global registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


class PluginTrust(str, Enum):
    DRAFT = "draft"
    EXPERIMENTAL = "experimental"
    VERIFIED_ON_FIXTURE = "verified_on_fixture"
    VERIFIED_ON_REAL_PROJECT = "verified_on_real_project"
    TRUSTED = "trusted"


@dataclass(frozen=True)
class PluginManifest:
    id: str
    kind: str
    language: str
    version: str
    file_extensions: tuple[str, ...] = ()
    manifest_files: tuple[str, ...] = ()
    activation: Mapping[str, Any] = field(default_factory=dict)
    supported_versions: tuple[str, ...] = ()
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    phases: tuple[str, ...] = ()
    entrypoint: str = ""
    cache_key: str = ""
    allowed_edge_kinds: tuple[str, ...] = ()
    confidence_policy: Mapping[str, Any] = field(default_factory=dict)
    evidence_requirements: Mapping[str, Any] = field(default_factory=dict)
    fixtures: tuple[str, ...] = ()
    local_first: bool = True
    path: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str | None = None) -> "PluginManifest":
        values = dict(data)
        return cls(
            id=str(values.get("id", "")),
            kind=str(values.get("kind", "")),
            language=str(values.get("language", "")),
            version=str(values.get("version", "")),
            file_extensions=tuple(str(x).lower() for x in values.get("file_extensions", ()) or ()),
            manifest_files=tuple(str(x).lower() for x in values.get("manifest_files", ()) or ()),
            activation=dict(values.get("activation", {}) or {}),
            supported_versions=tuple(str(x) for x in values.get("supported_versions", ()) or ()),
            capabilities=dict(values.get("capabilities", {}) or {}),
            phases=tuple(str(x) for x in values.get("phases", ()) or ()),
            entrypoint=str(values.get("entrypoint", "")),
            cache_key=str(values.get("cache_key", "")),
            allowed_edge_kinds=tuple(str(x) for x in values.get("allowed_edge_kinds", ()) or ()),
            confidence_policy=dict(values.get("confidence_policy", {}) or {}),
            evidence_requirements=dict(values.get("evidence_requirements", {}) or {}),
            fixtures=tuple(str(x) for x in values.get("fixtures", ()) or ()),
            local_first=bool(values.get("local_first", True)),
            path=path,
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id:
            errors.append("missing id")
        if self.kind not in {"language", "framework"}:
            errors.append("kind must be language or framework")
        if not self.language:
            errors.append("missing language")
        if not self.version:
            errors.append("missing version")
        if not self.entrypoint:
            errors.append("missing entrypoint")
        if not self.cache_key:
            errors.append("missing cache_key")
        if not self.local_first:
            errors.append("local_first must be true")
        if self.kind == "language" and not self.file_extensions and not self.manifest_files:
            errors.append("language plugin needs file_extensions or manifest_files")
        if self.kind == "framework" and not self.activation:
            errors.append("framework plugin needs activation rules")
        return errors


@dataclass(frozen=True)
class PluginDiagnostic:
    plugin_id: str
    severity: str
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass
class PluginContext:
    project_path: Path
    inventory: Mapping[str, Any]
    selected_plugins: tuple[str, ...] = ()
    cancellation: Any = None
    timeout_seconds: float = 30.0
    # Extraction is intentionally local and synchronous, but long projects still
    # need observable, cancellable work units.  Plugins report one completed
    # source file at a time through this callback; the pipeline owns aggregation.
    progress_callback: Callable[[Mapping[str, Any]], None] | None = None
    _diagnostics: list[PluginDiagnostic] = field(default_factory=list)

    @property
    def network_allowed(self) -> bool:
        return False

    @property
    def local_cache_root(self) -> Path:
        return self.project_path / ".impact_engine"

    def check_cancelled(self) -> None:
        if self.cancellation is not None and self.cancellation.is_set():
            raise TimeoutError("plugin execution cancelled")

    def report_progress(self, *, file: str | None = None, processed: int | None = None,
                        total: int | None = None, message: str = "") -> None:
        """Publish a best-effort local extraction heartbeat.

        This deliberately carries no source text.  It is only process-local
        progress metadata, so it preserves the local-first boundary.
        """
        if self.progress_callback is None:
            return
        payload: dict[str, Any] = {"message": message}
        if file is not None:
            payload["file"] = str(file).replace("\\\\", "/")
        if processed is not None:
            payload["processed"] = int(processed)
        if total is not None:
            payload["total"] = int(total)
        self.progress_callback(payload)

    def add_diagnostic(self, diagnostic: PluginDiagnostic) -> None:
        self._diagnostics.append(diagnostic)

    def diagnostics(self) -> tuple[PluginDiagnostic, ...]:
        return tuple(self._diagnostics)

    def write_local(self, relative_path: str, content: str) -> Path:
        """Write only inside the project-local Impact Engine cache."""
        target = (self.local_cache_root / relative_path).resolve()
        cache_root = self.local_cache_root.resolve()
        if target != cache_root and cache_root not in target.parents:
            raise PermissionError("plugin writes are restricted to .impact_engine")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target


@dataclass
class PluginResult:
    graph: Any = None
    facts: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)
    provenance: Mapping[str, Any] = field(default_factory=dict)


class Plugin(Protocol):
    manifest: PluginManifest

    def detect(self, context: PluginContext) -> bool: ...
    def plan(self, context: PluginContext) -> Mapping[str, Any]: ...
    def extract(self, context: PluginContext, files: Sequence[str] | None = None) -> PluginResult: ...
    def resolve(self, context: PluginContext, graph: Any) -> PluginResult: ...
    def validate(self, context: PluginContext, graph: Any) -> list[PluginDiagnostic]: ...
    def diagnostics(self) -> list[PluginDiagnostic]: ...


def load_entrypoint(value: str) -> Callable[..., Any]:
    module_name, separator, attribute = value.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"invalid plugin entrypoint: {value}")
    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)
