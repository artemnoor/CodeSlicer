"""Local-only review history and developer feedback."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def db_path(project_path: str | Path) -> Path:
    root = Path(project_path).expanduser().resolve()
    return root / ".impact_engine" / "impact_registry.sqlite"


def _connect(project_path: str | Path) -> sqlite3.Connection:
    path = db_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE IF NOT EXISTS review_history (
        review_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, project_path TEXT NOT NULL,
        schema_version TEXT NOT NULL, graph_fingerprint TEXT, risk_level TEXT,
        risk_score INTEGER, card_count INTEGER NOT NULL, warning_count INTEGER NOT NULL,
        summary_json TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS review_feedback (
        feedback_id TEXT PRIMARY KEY, review_id TEXT NOT NULL, created_at TEXT NOT NULL,
        value TEXT NOT NULL, reason TEXT, FOREIGN KEY(review_id) REFERENCES review_history(review_id)
    )""")
    conn.commit()
    return conn


def record_review(project_path: str | Path, report: dict[str, Any]) -> str:
    review_id = uuid.uuid4().hex
    summary = {
        "top_entity_ids": [item.get("entity_id") for item in report.get("top_impacts", [])],
        "coverage_statuses": [item.get("status") for item in report.get("coverage", [])],
        "suppressed_count": report.get("actions", {}).get("suppressed_count", 0),
    }
    with _connect(project_path) as conn:
        conn.execute("INSERT INTO review_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            review_id, datetime.now(timezone.utc).isoformat(), str(Path(project_path).resolve()),
            report.get("schema_version", "ReviewReport/v1"), report.get("graph_freshness", {}).get("fingerprint"),
            report.get("risk", {}).get("level"), int(report.get("risk", {}).get("score", 0)),
            len(report.get("top_impacts", [])), len(report.get("warnings", [])), json.dumps(summary, ensure_ascii=False),
        ))
    return review_id


def add_feedback(project_path: str | Path, review_id: str, value: str, reason: str | None = None) -> None:
    if value not in {"useful", "not useful", "ignored"}:
        raise ValueError("feedback value must be useful, not useful, or ignored")
    with _connect(project_path) as conn:
        exists = conn.execute("SELECT 1 FROM review_history WHERE review_id=?", (review_id,)).fetchone()
        if not exists:
            raise ValueError(f"unknown review_id: {review_id}")
        conn.execute("INSERT INTO review_feedback VALUES (?, ?, ?, ?, ?)", (uuid.uuid4().hex, review_id, datetime.now(timezone.utc).isoformat(), value, reason))


def list_history(project_path: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    with _connect(project_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM review_history ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
        return [dict(row) for row in rows]
