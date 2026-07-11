"""Machine-readable contracts for the local knowledge registry."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


TRUST_LEVELS = {
    "draft",
    "staged",
    "experimental",
    "verified_on_fixture",
    "verified_on_real_project",
    "trusted",
}


@dataclass
class LanguageProfileRecord:
    id: str
    display_name: str
    parser_kind: str
    version: str = "0.1.0"
    parser_package: str | None = None
    grammar_source_url: str | None = None
    profile: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    status: str = "experimental"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SupportPackRecord:
    ecosystem: str
    library: str
    version: str
    version_range: str
    trust_level: str
    pack: dict[str, Any]
    checksum_sha256: str
    source_urls: list[str] = field(default_factory=list)
    validation_summary: dict[str, Any] = field(default_factory=dict)
    status: str = "active"

    @property
    def pack_key(self) -> str:
        return f"{self.ecosystem.lower()}/{self.library.lower()}"

    @property
    def library_id(self) -> str:
        return self.pack_key

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pack_key"] = self.pack_key
        data["library_id"] = self.library_id
        return data


@dataclass
class ResearchRequestRecord:
    ecosystem: str
    library_name: str
    package_name: str | None = None
    requested_by: str = "impact-engine"
    project_fingerprint: str | None = None
    status: str = "queued"
    priority: int = 100
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
