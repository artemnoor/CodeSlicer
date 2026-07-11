"""Filesystem cache for local registry artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RegistryCache:
    def __init__(self, root: str | Path = ".impact_engine/registry_cache") -> None:
        self.root = Path(root)

    def write_json(self, relative_path: str, data: dict[str, Any]) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return path

    def read_json(self, relative_path: str) -> dict[str, Any] | None:
        path = self.root / relative_path
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def support_pack_path(self, ecosystem: str, library: str) -> str:
        return f"support_packs/{ecosystem.lower()}/{library.lower()}/support_pack.json"

    def language_profile_path(self, language_id: str) -> str:
        return f"languages/{language_id.lower()}/language_profile.json"
