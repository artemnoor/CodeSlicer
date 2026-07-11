"""Local knowledge registry backed by SQLite and a portable file cache."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from impact_engine.remote_registry.cache import RegistryCache
from impact_engine.remote_registry.models import (
    LanguageProfileRecord,
    ResearchRequestRecord,
    SupportPackRecord,
    TRUST_LEVELS,
)
from impact_engine.storage.registry import LocalRegistryStore
from impact_engine.support_packs.schema import validate_support_pack_dict


@dataclass
class RegistryConfig:
    cache_root: str = ".impact_engine/registry_cache"
    local_db_path: str | None = None

    @classmethod
    def from_env(cls) -> "RegistryConfig":
        return cls(
            cache_root=os.getenv("IMPACT_REGISTRY_CACHE_ROOT", ".impact_engine/registry_cache"),
            local_db_path=os.getenv("IMPACT_REGISTRY_LOCAL_DB", ".impact_engine/impact_registry.sqlite"),
        )


class RegistryClient:
    """Read and write all registry knowledge locally.

    SQLite is the source of truth. JSON cache files are kept as portable
    artifacts for research workflows and offline inspection.
    """

    def __init__(self, config: RegistryConfig | None = None) -> None:
        self.config = config or RegistryConfig.from_env()
        self.cache = RegistryCache(self.config.cache_root)
        self.local_db = LocalRegistryStore(self.config.local_db_path) if self.config.local_db_path else None

    def connection_status(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.local_db else "degraded",
            "mode": "sqlite" if self.local_db else "offline_cache",
            "database_path": self.config.local_db_path,
            "cache_root": self.config.cache_root,
        }

    def cache_language_profile(self, profile: LanguageProfileRecord | dict[str, Any]) -> str:
        if isinstance(profile, LanguageProfileRecord):
            data = profile.to_dict()
        elif hasattr(profile, "language_id"):
            data = {
                "id": profile.language_id,
                "display_name": profile.display_name,
                "parser_kind": profile.default_extractor_id,
                "profile": {
                    "file_extensions": sorted(profile.file_extensions),
                    "package_manifest_files": sorted(profile.package_manifest_files),
                    "standard_library_modules": sorted(profile.standard_library_modules),
                },
                "capabilities": profile.capabilities_dict(),
                "status": "experimental",
                "version": "0.1.0",
            }
        else:
            data = dict(profile)
        if self.local_db:
            self.local_db.save_language_profile(data)
        return str(self.cache.write_json(self.cache.language_profile_path(str(data["id"])), data).as_posix())

    def get_cached_language_profile(self, language_id: str) -> dict[str, Any] | None:
        if self.local_db:
            value = self.local_db.get_language_profile(language_id)
            if value:
                return value
        return self.cache.read_json(self.cache.language_profile_path(language_id))

    def cache_support_pack(self, pack: dict[str, Any]) -> dict[str, Any]:
        errors = validate_support_pack_dict(pack)
        if errors:
            return {"status": "error", "valid": False, "errors": errors}
        ecosystem = str(pack.get("ecosystem") or pack.get("language")).lower()
        library = str(pack["library"]).lower()
        if self.local_db:
            self.local_db.save_support_pack(self.support_pack_record_from_pack(pack).to_dict())
        path = self.cache.write_json(self.cache.support_pack_path(ecosystem, library), pack)
        return {"status": "cached", "valid": True, "path": str(path.as_posix()), "ecosystem": ecosystem, "library": library}

    def register_library(self, ecosystem: str, name: str, **metadata: Any) -> dict[str, Any]:
        if not self.local_db:
            return {"status": "local_db_unavailable", "library": f"{ecosystem}/{name}"}
        return self.local_db.register_library({"ecosystem": ecosystem, "name": name, **metadata})

    def library_status(self, ecosystem: str, name: str) -> dict[str, Any]:
        value = self.local_db.get_library(ecosystem, name) if self.local_db else None
        return {"status": "ok", "library": value} if value else {"status": "missing", "library": None}

    def list_languages(self) -> list[dict[str, Any]]:
        return self.local_db.list_languages() if self.local_db else []

    def list_libraries(self, ecosystem: str | None = None, status: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
        return self.local_db.list_libraries(ecosystem, status, search) if self.local_db else []

    def library_detail(self, ecosystem: str, name: str) -> dict[str, Any] | None:
        return self.local_db.get_library_detail(ecosystem, name) if self.local_db else None

    def list_documentation_sources(self, ecosystem: str | None = None, library: str | None = None) -> list[dict[str, Any]]:
        return self.local_db.list_documentation_sources(ecosystem, library) if self.local_db else []

    def list_research_requests(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.local_db.list_research_requests(status) if self.local_db else []

    def overview(self) -> dict[str, int]:
        if self.local_db:
            return self.local_db.registry_overview()
        return {"languages_count": 0, "libraries_count": 0, "trusted_packs_count": 0, "experimental_packs_count": 0, "pending_research_count": 0, "revalidation_candidates_count": 0}

    def get_cached_support_pack(self, ecosystem: str, library: str) -> dict[str, Any] | None:
        if self.local_db:
            value = self.local_db.get_support_pack(ecosystem, library)
            if value:
                return value
        return self.cache.read_json(self.cache.support_pack_path(ecosystem, library))

    def list_local_support_packs(self) -> list[dict[str, Any]]:
        return self.local_db.list_support_packs() if self.local_db else []

    def support_pack_record_from_pack(self, pack: dict[str, Any], *, version: str = "1.0.0") -> SupportPackRecord:
        errors = validate_support_pack_dict(pack)
        if errors:
            raise ValueError("; ".join(errors))
        trust_level = str(pack.get("trust_level") or pack.get("status") or "experimental")
        if trust_level not in TRUST_LEVELS:
            trust_level = "experimental"
        payload = json.dumps(pack, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return SupportPackRecord(
            ecosystem=str(pack.get("ecosystem") or pack.get("language")).lower(),
            library=str(pack["library"]).lower(),
            version=version,
            version_range=str(pack.get("version_range") or "*"),
            trust_level=trust_level,
            pack=pack,
            checksum_sha256=hashlib.sha256(payload).hexdigest(),
            source_urls=[str(item.get("url")) for item in pack.get("sources", []) if isinstance(item, dict) and item.get("url")],
            validation_summary={"status": "local_validation_pending"},
        )

    def create_research_request(self, request: ResearchRequestRecord | dict[str, Any]) -> dict[str, Any]:
        data = request.to_dict() if isinstance(request, ResearchRequestRecord) else dict(request)
        data = {key: data.get(key) for key in (
            "ecosystem", "library_name", "package_name", "requested_by",
            "project_fingerprint", "status", "priority", "input", "output", "error"
        )}
        if self.local_db:
            self.local_db.register_library({
                "ecosystem": data["ecosystem"],
                "name": data["library_name"],
                "status": "research_requested",
                "metadata": {"package_name": data.get("package_name")},
            })
            result = self.local_db.save_research_request(data)
            path = self.cache.write_json(
                f"research_requests/{data['ecosystem'].lower()}/{data['library_name'].lower()}/request.json",
                data,
            )
            result["path"] = str(path.as_posix())
            return result
        path = self.cache.write_json(
            f"research_requests/{data['ecosystem'].lower()}/{data['library_name'].lower()}/request.json",
            data,
        )
        return {"status": "queued_local", "path": str(path.as_posix()), "request": data}

    def approve_support_pack(self, pack_id: str, trust_level: str, reviewer: str, note: str | None = None) -> dict[str, Any]:
        if trust_level not in TRUST_LEVELS:
            return {"status": "error", "error": f"Unknown trust level: {trust_level}"}
        if self.local_db:
            return self.local_db.transition_support_pack(pack_id, trust_level, reviewer, note)
        return {"status": "error", "error": "Local registry database is unavailable"}

    def record_documentation_check(self, ecosystem: str, library: str, url: str, content_hash: str, source_type: str = "docs") -> dict[str, Any]:
        if self.local_db:
            return self.local_db.record_doc_source_check({
                "ecosystem": ecosystem, "library_name": library, "url": url,
                "content_hash": content_hash, "source_type": source_type,
            })
        return {"status": "error", "error": "Local registry database is unavailable"}

    def revalidation_candidates(self) -> list[dict[str, Any]]:
        return self.local_db.list_revalidation_candidates() if self.local_db else []

    def simulate_library_lifecycle(self, ecosystem: str, library: str, source_url: str) -> dict[str, Any]:
        self.register_library(ecosystem, library, docs_url=source_url, status="unknown")
        request = self.create_research_request(ResearchRequestRecord(ecosystem=ecosystem, library_name=library, input={"source_plan": [source_url]}))
        return {"status": "ok", "steps": ["library_registered", "research_requested"], "request": request, "library": self.library_status(ecosystem, library)}

    def pull_support_pack(self, ecosystem: str, library: str) -> dict[str, Any]:
        cached = self.get_cached_support_pack(ecosystem, library)
        if cached:
            return {"status": "ok", "source": "local_db" if self.local_db else "cache", "support_pack": cached}
        return {"status": "missing", "source": "none", "support_pack": None}


PathLikeString = str
