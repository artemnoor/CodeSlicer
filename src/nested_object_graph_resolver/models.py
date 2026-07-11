"""Small dataclass models used by the resolver.

The package deliberately avoids pydantic and any runtime dependencies.  The
public function still accepts and returns plain JSON-compatible dictionaries;
these dataclasses are only an internal convenience layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


PathPart = str | tuple[str, str]
Path = tuple[PathPart, ...]


@dataclass(frozen=True)
class TypeBinding:
    """A deterministic or inferred binding from an object path to a type."""

    owner_type: str
    path: tuple[str, ...]
    target_type: str
    confidence: float = 0.75
    source: str = "INFERRED"
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def key(self) -> tuple[str, tuple[str, ...], str]:
        return (self.owner_type, self.path, self.target_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_type": self.owner_type,
            "path": list(self.path),
            "field": ".".join(self.path) if self.path else "",
            "target_type": self.target_type,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class DictEntryBinding:
    """A binding from a map path and literal key to a value type."""

    owner_type: str
    path: tuple[str, ...]
    key_name: str
    target_type: str
    confidence: float = 0.75
    source: str = "INFERRED"
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def key(self) -> tuple[str, tuple[str, ...], str, str]:
        return (self.owner_type, self.path, self.key_name, self.target_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_type": self.owner_type,
            "path": list(self.path),
            "dict": ".".join(self.path),
            "key": self.key_name,
            "target_type": self.target_type,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ProviderBinding:
    """A binding from a provider expression to the type it returns."""

    provider_path: Path
    returns: str
    confidence: float = 0.8
    source: str = "INFERRED"
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def key(self) -> tuple[Path, str]:
        return (self.provider_path, self.returns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": path_to_string(self.provider_path),
            "returns": self.returns,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class AliasBinding:
    """A binding from one object path to another object path."""

    scope: str
    owner_type: str | None
    alias_path: Path
    target_path: Path
    confidence: float = 0.85
    source: str = "INFERRED"
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def key(self) -> tuple[str, Path, Path]:
        # Field aliases are reusable across methods through owner_type; local
        # aliases are scoped to one method/constructor.
        namespace = self.owner_type if self.alias_path and self.alias_path[0] == "self" else self.scope
        return (namespace or self.scope, self.alias_path, self.target_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "owner_type": self.owner_type,
            "alias": path_to_string(self.alias_path),
            "target": path_to_string(self.target_path),
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "evidence": list(self.evidence),
        }


@dataclass
class PathResolution:
    """Result of resolving a receiver chain to one or more possible types."""

    types: set[str] = field(default_factory=set)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "unresolved"
    rejected: bool = False


@dataclass
class Edge:
    """Resolved call edge."""

    from_id: str
    to_id: str
    kind: str = "CALLS"
    confidence: float = 0.0
    source: str = "INFERRED"
    status: str = "weak"
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_id,
            "to": self.to_id,
            "kind": self.kind,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "status": self.status,
            "evidence": list(self.evidence),
            "warnings": list(self.warnings),
        }


def clamp_confidence(value: Any, default: float = 0.75) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def canonical_key_component(value: Any) -> tuple[str, str] | None:
    if isinstance(value, dict) and "key" in value:
        return ("key", str(value["key"]))
    return None


def path_to_string(path: Iterable[PathPart]) -> str:
    out = ""
    for part in path:
        if isinstance(part, tuple):
            out += f"[{part[1]!r}]"
        elif not out:
            out = str(part)
        else:
            out += f".{part}"
    return out
