"""Language Profile and semantic provider models."""
from dataclasses import dataclass, field
from typing import Set


@dataclass(frozen=True)
class LanguageSemanticCapabilities:
    structural_extraction: bool = False
    import_resolution: bool = False
    call_resolution: str = "none"
    endpoint_resolution: bool = False
    framework_rules: bool = False
    production_semantic_baseline: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "structural_extraction": self.structural_extraction,
            "import_resolution": self.import_resolution,
            "call_resolution": self.call_resolution,
            "endpoint_resolution": self.endpoint_resolution,
            "framework_rules": self.framework_rules,
            "production_semantic_baseline": self.production_semantic_baseline,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class LanguageSemanticProvider:
    language_id: str
    provider_id: str
    capabilities: LanguageSemanticCapabilities
    confidence_policy: str
    diagnostics_label: str

    def to_dict(self) -> dict:
        return {
            "language_id": self.language_id,
            "provider_id": self.provider_id,
            "capabilities": self.capabilities.to_dict(),
            "confidence_policy": self.confidence_policy,
            "diagnostics_label": self.diagnostics_label,
        }


@dataclass
class LanguageProfile:
    language_id: str
    display_name: str
    file_extensions: Set[str] = field(default_factory=set)
    package_manifest_files: Set[str] = field(default_factory=set)
    standard_library_modules: Set[str] = field(default_factory=set)
    default_extractor_id: str = "unknown"
    semantic_provider: LanguageSemanticProvider | None = None

    def capabilities_dict(self) -> dict:
        if not self.semantic_provider:
            return {}
        return self.semantic_provider.to_dict()
