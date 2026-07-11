"""Dataclass models used internally by the resolver.

The package intentionally avoids pydantic or any runtime dependency. Every model
can be converted to JSON-compatible dictionaries through ``to_dict``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EdgeStatus = Literal["confirmed", "likely", "weak", "suspicious", "rejected"]
EdgeSource = Literal["FACT", "INFERRED", "RULE", "CANONICALIZED"]


@dataclass(frozen=True)
class CanonicalRoute:
    """Normalized HTTP route path plus optional normalized query metadata."""

    raw: str
    path: str
    query: str = ""
    dynamic_segments: int = 0
    had_trailing_slash: bool = False

    @property
    def key(self) -> str:
        return self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "path": self.path,
            "query": self.query,
            "dynamic_segments": self.dynamic_segments,
            "had_trailing_slash": self.had_trailing_slash,
        }


@dataclass
class EvalResult:
    """Result of evaluating a path expression fact."""

    value: str | None
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None

    def merge(self, other: "EvalResult") -> "EvalResult":
        value = (self.value or "") + (other.value or "") if self.ok and other.ok else None
        return EvalResult(
            value=value,
            confidence=min(self.confidence, other.confidence),
            evidence=[*self.evidence, *other.evidence],
            warnings=[*self.warnings, *other.warnings],
            unresolved=[*self.unresolved, *other.unresolved],
        )

    def with_confidence(self, confidence: float) -> "EvalResult":
        return EvalResult(
            value=self.value,
            confidence=min(self.confidence, confidence),
            evidence=list(self.evidence),
            warnings=list(self.warnings),
            unresolved=list(self.unresolved),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
            "unresolved": list(self.unresolved),
        }


@dataclass(frozen=True)
class WrapperRecipe:
    """Declarative HTTP wrapper recipe.

    Supported recipe styles:
    - fixed method + URL argument: postJson(url, payload)
    - method argument + URL argument: request("POST", url, payload)
    - object config argument: client.request({"method": "POST", "url": url})
    - fetch-style options argument: fetch(url, {"method": "POST"})
    """

    wrapper_name: str
    method: str | None = None
    url_arg_index: int | None = None
    method_arg_index: int | None = None
    object_config_arg_index: int | None = None
    url_object_key: str = "url"
    method_object_key: str = "method"
    options_arg_index: int | None = None
    default_method: str | None = None
    confidence: float = 0.86
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WrapperRecipe":
        return cls(
            wrapper_name=str(data["wrapper_name"]),
            method=data.get("method"),
            url_arg_index=data.get("url_arg_index"),
            method_arg_index=data.get("method_arg_index"),
            object_config_arg_index=data.get("object_config_arg_index"),
            url_object_key=data.get("url_object_key", "url"),
            method_object_key=data.get("method_object_key", "method"),
            options_arg_index=data.get("options_arg_index"),
            default_method=data.get("default_method"),
            confidence=float(data.get("confidence", 0.86)),
            description=data.get("description", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "wrapper_name": self.wrapper_name,
            "method": self.method,
            "url_arg_index": self.url_arg_index,
            "method_arg_index": self.method_arg_index,
            "object_config_arg_index": self.object_config_arg_index,
            "url_object_key": self.url_object_key,
            "method_object_key": self.method_object_key,
            "options_arg_index": self.options_arg_index,
            "default_method": self.default_method,
            "confidence": self.confidence,
            "description": self.description,
        }


@dataclass
class WrapperResolution:
    """A matched HTTP wrapper call before path expression evaluation."""

    method: str
    url_expr: Any
    confidence: float
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url_expr": self.url_expr,
            "confidence": round(self.confidence, 4),
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class BackendRoute:
    method: str
    path: str
    handler: str
    framework: str = "unknown"
    confidence: float = 0.9
    service: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def http_node_id(self, canonical_path: str) -> str:
        return f"HTTP {self.method.upper()} {canonical_path}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.upper(),
            "path": self.path,
            "handler": self.handler,
            "framework": self.framework,
            "confidence": self.confidence,
            "service": self.service,
        }


@dataclass
class HttpEndpointNode:
    method: str
    path: str
    id: str | None = None
    query: str = ""
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    service: str = ""

    def __post_init__(self) -> None:
        self.method = self.method.upper()
        if self.id is None:
            self.id = f"{self.service}:{self.method}:{self.path}" if self.service else f"HTTP {self.method} {self.path}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "path": self.path,
            "query": self.query,
            "confidence": round(self.confidence, 4),
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
            "service": self.service,
        }


@dataclass
class Edge:
    from_id: str
    to_id: str
    kind: str
    confidence: float
    source: EdgeSource = "INFERRED"
    status: EdgeStatus = "weak"
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_id,
            "to": self.to_id,
            "kind": self.kind,
            "confidence": round(max(0.0, min(1.0, self.confidence)), 4),
            "source": self.source,
            "status": self.status,
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }
