from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class _StrEnum(str, Enum):
    """str Enum with predictable JSON representation through explicit to_dict."""

    def __str__(self) -> str:  # pragma: no cover - defensive convenience
        return self.value


class FileRole(_StrEnum):
    SOURCE = "SOURCE"
    TEST = "TEST"
    GENERATED = "GENERATED"
    CONFIG = "CONFIG"
    DOCS = "DOCS"
    MIGRATION = "MIGRATION"
    FIXTURE = "FIXTURE"
    CONTRACT = "CONTRACT"
    VENDOR = "VENDOR"
    BUILD_ARTIFACT = "BUILD_ARTIFACT"
    UNKNOWN = "UNKNOWN"


class Reachability(_StrEnum):
    RUNTIME = "RUNTIME"
    TEST_ONLY = "TEST_ONLY"
    GENERATED_ONLY = "GENERATED_ONLY"
    UNREACHABLE_CANDIDATE = "UNREACHABLE_CANDIDATE"
    UNKNOWN = "UNKNOWN"


class DependencyKind(_StrEnum):
    STDLIB = "STDLIB"
    LOCAL = "LOCAL"
    DECLARED_THIRD_PARTY = "DECLARED_THIRD_PARTY"
    KNOWN_COMMON_THIRD_PARTY = "KNOWN_COMMON_THIRD_PARTY"
    UNKNOWN_THIRD_PARTY = "UNKNOWN_THIRD_PARTY"
    BUILTIN_RUNTIME = "BUILTIN_RUNTIME"
    DEV_ONLY = "DEV_ONLY"
    TYPE_ONLY = "TYPE_ONLY"


class RouteParamStyle(_StrEnum):
    BRACE = "BRACE"
    COLON = "COLON"
    ANGLE = "ANGLE"
    TEMPLATE = "TEMPLATE"
    EXPRESS = "EXPRESS"
    UNKNOWN = "UNKNOWN"


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value)


def _enum_from(enum_cls: type[Enum], value: Any) -> Any:
    if isinstance(value, enum_cls):
        return value
    return enum_cls(str(value))


@dataclass(slots=True)
class ProjectFile:
    path: str
    content: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "content": self.content}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectFile":
        return cls(path=str(data["path"]), content=data.get("content"))


@dataclass(slots=True)
class FileClassification:
    path: str
    role: FileRole
    confidence: float
    reasons: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    is_generated: bool = False
    is_test: bool = False
    is_contract: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "role": self.role.value,
            "confidence": float(self.confidence),
            "reasons": list(self.reasons),
            "tags": list(self.tags),
            "language": self.language,
            "is_generated": bool(self.is_generated),
            "is_test": bool(self.is_test),
            "is_contract": bool(self.is_contract),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FileClassification":
        return cls(
            path=str(data["path"]),
            role=_enum_from(FileRole, data["role"]),
            confidence=float(data.get("confidence", 0.0)),
            reasons=[str(x) for x in _as_list(data.get("reasons"))],
            tags=[str(x) for x in _as_list(data.get("tags"))],
            language=data.get("language"),
            is_generated=bool(data.get("is_generated", False)),
            is_test=bool(data.get("is_test", False)),
            is_contract=bool(data.get("is_contract", False)),
        )


@dataclass(slots=True)
class DependencyClassification:
    name: str
    ecosystem: str
    kind: DependencyKind
    confidence: float
    reasons: list[str] = field(default_factory=list)
    declared: bool = False
    local: bool = False
    requires_research: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ecosystem": self.ecosystem,
            "kind": self.kind.value,
            "confidence": float(self.confidence),
            "reasons": list(self.reasons),
            "declared": bool(self.declared),
            "local": bool(self.local),
            "requires_research": bool(self.requires_research),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyClassification":
        return cls(
            name=str(data["name"]),
            ecosystem=str(data["ecosystem"]),
            kind=_enum_from(DependencyKind, data["kind"]),
            confidence=float(data.get("confidence", 0.0)),
            reasons=[str(x) for x in _as_list(data.get("reasons"))],
            declared=bool(data.get("declared", False)),
            local=bool(data.get("local", False)),
            requires_research=bool(data.get("requires_research", False)),
        )


@dataclass(slots=True)
class CanonicalRoute:
    method: str | None
    original: str
    canonical_path: str
    param_names: list[str] = field(default_factory=list)
    confidence: float = 0.3
    reasons: list[str] = field(default_factory=list)
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "original": self.original,
            "canonical_path": self.canonical_path,
            "param_names": list(self.param_names),
            "confidence": float(self.confidence),
            "reasons": list(self.reasons),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalRoute":
        return cls(
            method=data.get("method"),
            original=str(data["original"]),
            canonical_path=str(data["canonical_path"]),
            param_names=[str(x) for x in _as_list(data.get("param_names"))],
            confidence=float(data.get("confidence", 0.3)),
            reasons=[str(x) for x in _as_list(data.get("reasons"))],
            source=data.get("source"),
        )


@dataclass(slots=True)
class GraphNodeAnnotation:
    node_id: str
    file_path: str | None
    file_role: FileRole | None
    reachability: Reachability
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "file_path": self.file_path,
            "file_role": self.file_role.value if self.file_role else None,
            "reachability": self.reachability.value,
            "tags": list(self.tags),
            "confidence": float(self.confidence),
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphNodeAnnotation":
        role = data.get("file_role")
        return cls(
            node_id=str(data["node_id"]),
            file_path=data.get("file_path"),
            file_role=_enum_from(FileRole, role) if role is not None else None,
            reachability=_enum_from(Reachability, data["reachability"]),
            tags=[str(x) for x in _as_list(data.get("tags"))],
            confidence=float(data.get("confidence", 0.0)),
            reasons=[str(x) for x in _as_list(data.get("reasons"))],
        )


@dataclass(slots=True)
class GraphEdgeAnnotation:
    edge_id: str
    reachability: Reachability
    noise_score: float
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "reachability": self.reachability.value,
            "noise_score": float(self.noise_score),
            "tags": list(self.tags),
            "confidence": float(self.confidence),
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphEdgeAnnotation":
        return cls(
            edge_id=str(data["edge_id"]),
            reachability=_enum_from(Reachability, data["reachability"]),
            noise_score=float(data.get("noise_score", 0.0)),
            tags=[str(x) for x in _as_list(data.get("tags"))],
            confidence=float(data.get("confidence", 0.0)),
            reasons=[str(x) for x in _as_list(data.get("reasons"))],
        )


@dataclass(slots=True)
class HygieneReport:
    files: list[FileClassification] = field(default_factory=list)
    dependencies: list[DependencyClassification] = field(default_factory=list)
    routes: list[CanonicalRoute] = field(default_factory=list)
    node_annotations: list[GraphNodeAnnotation] = field(default_factory=list)
    edge_annotations: list[GraphEdgeAnnotation] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": [x.to_dict() for x in self.files],
            "dependencies": [x.to_dict() for x in self.dependencies],
            "routes": [x.to_dict() for x in self.routes],
            "node_annotations": [x.to_dict() for x in self.node_annotations],
            "edge_annotations": [x.to_dict() for x in self.edge_annotations],
            "diagnostics": list(self.diagnostics),
            "summary": {str(k): int(v) for k, v in self.summary.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HygieneReport":
        return cls(
            files=[FileClassification.from_dict(x) for x in _as_list(data.get("files"))],
            dependencies=[DependencyClassification.from_dict(x) for x in _as_list(data.get("dependencies"))],
            routes=[CanonicalRoute.from_dict(x) for x in _as_list(data.get("routes"))],
            node_annotations=[GraphNodeAnnotation.from_dict(x) for x in _as_list(data.get("node_annotations"))],
            edge_annotations=[GraphEdgeAnnotation.from_dict(x) for x in _as_list(data.get("edge_annotations"))],
            diagnostics=[str(x) for x in _as_list(data.get("diagnostics"))],
            summary={str(k): int(v) for k, v in dict(data.get("summary", {})).items()},
        )
