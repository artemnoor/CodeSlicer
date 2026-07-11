"""SQLite-backed local knowledge registry."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class LocalRegistryStore:
    """Stores registry records locally without making the analyzer network-bound."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS registry_languages (
                    id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                    parser_kind TEXT NOT NULL, parser_package TEXT,
                    grammar_source_url TEXT, profile_json TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL, status TEXT NOT NULL,
                    version TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS registry_libraries (
                    id TEXT PRIMARY KEY, ecosystem TEXT NOT NULL, name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL, package_manager TEXT,
                    homepage_url TEXT, repository_url TEXT, docs_url TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ecosystem, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS registry_support_pack_versions (
                    id TEXT PRIMARY KEY, library_id TEXT NOT NULL,
                    pack_key TEXT NOT NULL, version TEXT NOT NULL,
                    version_range TEXT NOT NULL, trust_level TEXT NOT NULL,
                    status TEXT NOT NULL, pack_json TEXT NOT NULL,
                    checksum_sha256 TEXT NOT NULL, source_urls_json TEXT NOT NULL,
                    validation_summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(pack_key, version)
                );
                CREATE TABLE IF NOT EXISTS registry_research_requests (
                    id TEXT PRIMARY KEY, ecosystem TEXT NOT NULL,
                    library_name TEXT NOT NULL, package_name TEXT,
                    requested_by TEXT NOT NULL, project_fingerprint TEXT,
                    status TEXT NOT NULL, priority INTEGER NOT NULL,
                    input_json TEXT NOT NULL, output_json TEXT NOT NULL,
                    error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS registry_validation_runs (
                    id TEXT PRIMARY KEY, support_pack_version_id TEXT,
                    research_request_id TEXT, status TEXT NOT NULL,
                    fixture_ref TEXT, project_ref TEXT, report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS registry_doc_sources (
                    id TEXT PRIMARY KEY, ecosystem TEXT NOT NULL,
                    library_name TEXT NOT NULL, url TEXT NOT NULL,
                    source_type TEXT NOT NULL, content_hash TEXT,
                    last_checked_at TEXT, last_changed_at TEXT,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(ecosystem, library_name, url)
                );
                """
            )
            self._ensure_columns(conn, "registry_libraries", {
                "status": "TEXT NOT NULL DEFAULT 'unknown'",
                "latest_version": "TEXT",
                "last_checked_at": "TEXT",
                "last_changed_at": "TEXT",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            })
            self._ensure_columns(conn, "registry_support_pack_versions", {
                "documentation_hash": "TEXT",
                "approved_by": "TEXT",
                "approved_at": "TEXT",
                "supersedes_id": "TEXT",
                "revalidation_due_at": "TEXT",
            })

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def register_library(self, data: dict[str, Any]) -> dict[str, Any]:
        library_id = data.get("id") or f"{data['ecosystem'].lower()}/{data['name'].lower()}"
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO registry_libraries
                (id, ecosystem, name, normalized_name, package_manager, homepage_url,
                 repository_url, docs_url, status, latest_version, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(ecosystem, normalized_name) DO UPDATE SET
                  package_manager=COALESCE(excluded.package_manager, registry_libraries.package_manager),
                  homepage_url=COALESCE(excluded.homepage_url, registry_libraries.homepage_url),
                  repository_url=COALESCE(excluded.repository_url, registry_libraries.repository_url),
                  docs_url=COALESCE(excluded.docs_url, registry_libraries.docs_url),
                  status=excluded.status, latest_version=excluded.latest_version,
                  metadata_json=excluded.metadata_json, updated_at=CURRENT_TIMESTAMP""",
                (library_id, data["ecosystem"].lower(), data["name"], data["name"].lower(),
                 data.get("package_manager"), data.get("homepage_url"), data.get("repository_url"),
                 data.get("docs_url"), data.get("status", "unknown"), data.get("latest_version"),
                 json.dumps(data.get("metadata", {}), ensure_ascii=False)),
            )
        return {"status": "ok", "library_id": library_id}

    def get_library(self, ecosystem: str, name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM registry_libraries WHERE ecosystem=? AND normalized_name=?",
                (ecosystem.lower(), name.lower()),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json", "{}"))
        return data

    def list_libraries(self, ecosystem: str | None = None, status: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if ecosystem:
            clauses.append("ecosystem=?"); params.append(ecosystem.lower())
        if status:
            clauses.append("status=?"); params.append(status)
        if search:
            clauses.append("normalized_name LIKE ?"); params.append(f"%{search.lower()}%")
        query = "SELECT * FROM registry_libraries"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY ecosystem, normalized_name"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["metadata"] = json.loads(data.pop("metadata_json", "{}"))
            result.append(data)
        return result

    def list_languages(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM registry_languages ORDER BY id").fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["profile"] = json.loads(data.pop("profile_json"))
            data["capabilities"] = json.loads(data.pop("capabilities_json"))
            result.append(data)
        return result

    def get_library_detail(self, ecosystem: str, name: str) -> dict[str, Any] | None:
        library = self.get_library(ecosystem, name)
        if not library:
            return None
        key = f"{ecosystem.lower()}/{name.lower()}"
        with self._connect() as conn:
            packs = conn.execute("SELECT * FROM registry_support_pack_versions WHERE pack_key=? ORDER BY created_at DESC", (key,)).fetchall()
            requests = conn.execute("SELECT * FROM registry_research_requests WHERE ecosystem=? AND lower(library_name)=? ORDER BY created_at DESC", (ecosystem.lower(), name.lower())).fetchall()
            sources = conn.execute("SELECT * FROM registry_doc_sources WHERE ecosystem=? AND lower(library_name)=? ORDER BY url", (ecosystem.lower(), name.lower())).fetchall()
        def row_json(row: sqlite3.Row) -> dict[str, Any]:
            data = dict(row)
            for field in ("pack_json", "source_urls_json", "validation_summary_json", "input_json", "output_json", "metadata_json"):
                if field in data:
                    data[field.removesuffix("_json")] = json.loads(data.pop(field) or "{}")
            return data
        return {"library": library, "support_packs": [row_json(row) for row in packs], "research_requests": [row_json(row) for row in requests], "documentation_sources": [row_json(row) for row in sources]}

    def list_documentation_sources(self, ecosystem: str | None = None, library: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if ecosystem:
            clauses.append("ecosystem=?"); params.append(ecosystem.lower())
        if library:
            clauses.append("lower(library_name)=?"); params.append(library.lower())
        query = "SELECT * FROM registry_doc_sources" + ((" WHERE " + " AND ".join(clauses)) if clauses else "") + " ORDER BY ecosystem, library_name, url"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def list_research_requests(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM registry_research_requests"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"; params.append(status)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["input"] = json.loads(data.pop("input_json") or "{}")
            data["output"] = json.loads(data.pop("output_json") or "{}")
            result.append(data)
        return result

    def registry_overview(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "languages_count": conn.execute("SELECT COUNT(*) FROM registry_languages").fetchone()[0],
                "libraries_count": conn.execute("SELECT COUNT(*) FROM registry_libraries").fetchone()[0],
                "trusted_packs_count": conn.execute("SELECT COUNT(*) FROM registry_support_pack_versions WHERE trust_level='trusted' AND status='active'").fetchone()[0],
                "experimental_packs_count": conn.execute("SELECT COUNT(*) FROM registry_support_pack_versions WHERE trust_level='experimental' AND status='active'").fetchone()[0],
                "pending_research_count": conn.execute("SELECT COUNT(*) FROM registry_research_requests WHERE status IN ('queued','researching')").fetchone()[0],
                "revalidation_candidates_count": conn.execute("SELECT COUNT(*) FROM registry_doc_sources WHERE last_changed_at IS NOT NULL").fetchone()[0],
            }

    def set_library_status(self, ecosystem: str, name: str, status: str, **metadata: Any) -> dict[str, Any]:
        library = self.get_library(ecosystem, name)
        if not library:
            self.register_library({"ecosystem": ecosystem, "name": name, "status": status, "metadata": metadata})
        else:
            merged = dict(library.get("metadata", {}))
            merged.update(metadata)
            with self._connect() as conn:
                conn.execute(
                    "UPDATE registry_libraries SET status=?, metadata_json=?, updated_at=CURRENT_TIMESTAMP WHERE ecosystem=? AND normalized_name=?",
                    (status, json.dumps(merged, ensure_ascii=False), ecosystem.lower(), name.lower()),
                )
        return {"status": "ok", "library_status": status, "ecosystem": ecosystem.lower(), "library": name.lower()}

    def save_language_profile(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO registry_languages
                (id, display_name, parser_kind, parser_package, grammar_source_url,
                 profile_json, capabilities_json, status, version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (data["id"], data["display_name"], data["parser_kind"], data.get("parser_package"),
                 data.get("grammar_source_url"), json.dumps(data.get("profile", {})),
                 json.dumps(data.get("capabilities", {})), data.get("status", "experimental"),
                 data.get("version", "0.1.0")),
            )

    def get_language_profile(self, language_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM registry_languages WHERE id = ?", (language_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["profile"] = json.loads(data.pop("profile_json"))
        data["capabilities"] = json.loads(data.pop("capabilities_json"))
        return data

    def save_support_pack(self, record: dict[str, Any]) -> None:
        pack_key = record.get("pack_key") or f"{record['ecosystem']}/{record['library']}"
        library_id = record.get("library_id") or pack_key
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO registry_libraries
                (id, ecosystem, name, normalized_name) VALUES (?, ?, ?, ?)""",
                (library_id, record["ecosystem"], record["library"], record["library"].lower()),
            )
            conn.execute(
                """INSERT OR REPLACE INTO registry_support_pack_versions
                (id, library_id, pack_key, version, version_range, trust_level, status,
                 pack_json, checksum_sha256, source_urls_json, validation_summary_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.get("id") or f"{pack_key}@{record['version']}", library_id, pack_key,
                 record["version"], record.get("version_range", "*"), record["trust_level"],
                 record.get("status", "active"), json.dumps(record["pack"], ensure_ascii=False),
                 record["checksum_sha256"], json.dumps(record.get("source_urls", [])),
                 json.dumps(record.get("validation_summary", {}))),
            )
            conn.execute(
                "UPDATE registry_libraries SET status=?, latest_version=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (record.get("library_status", "experimental"), record["version"], library_id),
            )

    def get_support_pack(self, ecosystem: str, library: str) -> dict[str, Any] | None:
        key = f"{ecosystem.lower()}/{library.lower()}"
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM registry_support_pack_versions
                WHERE pack_key = ? AND status = 'active'
                ORDER BY created_at DESC LIMIT 1""", (key,)
            ).fetchone()
        if not row:
            return None
        return json.loads(row["pack_json"])

    def list_support_packs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pack_json FROM registry_support_pack_versions "
                "WHERE status = 'active' ORDER BY pack_key, created_at DESC"
            ).fetchall()
        return [json.loads(row["pack_json"]) for row in rows]

    def save_research_request(self, data: dict[str, Any]) -> dict[str, Any]:
        request_id = data.get("id") or f"{data['ecosystem']}/{data['library_name']}"
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO registry_research_requests
                (id, ecosystem, library_name, package_name, requested_by,
                 project_fingerprint, status, priority, input_json, output_json, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (request_id, data["ecosystem"], data["library_name"], data.get("package_name"),
                 data.get("requested_by", "impact-engine"), data.get("project_fingerprint"),
                 data.get("status", "queued"), data.get("priority", 100),
                 json.dumps(data.get("input", {}), ensure_ascii=False),
                json.dumps(data.get("output", {}), ensure_ascii=False), data.get("error")),
            )
        self.set_library_status(data["ecosystem"], data["library_name"], "research_requested", research_request_id=request_id)
        return {"status": "queued_local_db", "id": request_id}

    def transition_support_pack(self, pack_id: str, trust_level: str, reviewer: str | None = None, note: str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM registry_support_pack_versions WHERE id=?", (pack_id,)).fetchone()
            if not row:
                return {"status": "missing", "pack_id": pack_id}
            metadata = json.loads(row["validation_summary_json"] or "{}")
            metadata["trust_transition"] = {"reviewer": reviewer, "note": note, "trust_level": trust_level}
            conn.execute(
                "UPDATE registry_support_pack_versions SET trust_level=?, validation_summary_json=?, approved_by=?, approved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (trust_level, json.dumps(metadata, ensure_ascii=False), reviewer, pack_id),
            )
            pack_key = str(row["pack_key"])
            if "/" in pack_key:
                ecosystem, library = pack_key.split("/", 1)
                conn.execute(
                    "UPDATE registry_libraries SET status=?, updated_at=CURRENT_TIMESTAMP WHERE ecosystem=? AND normalized_name=?",
                    (trust_level, ecosystem, library),
                )
        return {"status": "ok", "pack_id": pack_id, "trust_level": trust_level}

    def list_revalidation_candidates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM registry_doc_sources WHERE last_changed_at IS NOT NULL ORDER BY last_changed_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def record_doc_source_check(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn:
            old = conn.execute(
                "SELECT content_hash FROM registry_doc_sources WHERE ecosystem=? AND library_name=? AND url=?",
                (data["ecosystem"], data["library_name"], data["url"]),
            ).fetchone()
            changed = bool(old and old[0] != data.get("content_hash"))
            conn.execute(
                """INSERT INTO registry_doc_sources
                (id, ecosystem, library_name, url, source_type, content_hash, last_checked_at, last_changed_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, ?)
                ON CONFLICT(ecosystem, library_name, url) DO UPDATE SET
                  content_hash=excluded.content_hash, last_checked_at=CURRENT_TIMESTAMP,
                  last_changed_at=CASE WHEN registry_doc_sources.content_hash != excluded.content_hash THEN CURRENT_TIMESTAMP ELSE registry_doc_sources.last_changed_at END,
                  metadata_json=excluded.metadata_json""",
                (data.get("id") or f"{data['ecosystem']}/{data['library_name']}/{data['url']}", data["ecosystem"], data["library_name"], data["url"], data.get("source_type", "docs"), data.get("content_hash"), changed, json.dumps(data.get("metadata", {}), ensure_ascii=False)),
            )
        return {"status": "ok", "changed": changed}
