"""SQLite DB interface operations. Stage 12."""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from impact_engine.storage.schema import (
    CREATE_ANALYSIS_RUNS,
    CREATE_DETECTED_LIBRARIES,
    CREATE_SUPPORT_PACKS,
    CREATE_RESEARCH_WORKFLOWS
)


def get_default_db_path() -> Path:
    return Path(".impact_engine") / "impact_engine.sqlite"


def init_db(db_path: str | Path | None = None) -> Path:
    if db_path is None:
        db_path = get_default_db_path()
    else:
        db_path = Path(db_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(CREATE_ANALYSIS_RUNS)
        cursor.execute(CREATE_DETECTED_LIBRARIES)
        cursor.execute(CREATE_SUPPORT_PACKS)
        cursor.execute(CREATE_RESEARCH_WORKFLOWS)
        conn.commit()
    finally:
        conn.close()
    return db_path


def record_analysis_run(db_path: str | Path, run_id: str, project_path: str, status: str, nodes: int, edges: int, metadata_dict: dict | None = None) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        meta_str = json.dumps(metadata_dict) if metadata_dict is not None else None
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT OR REPLACE INTO analysis_runs (run_id, timestamp, project_path, status, nodes, edges, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, timestamp, project_path, status, nodes, edges, meta_str)
        )
        conn.commit()
    finally:
        conn.close()


def list_analysis_runs(db_path: str | Path) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM analysis_runs ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        runs = []
        for r in rows:
            meta = None
            if r["metadata"]:
                try:
                    meta = json.loads(r["metadata"])
                except Exception:
                    pass
            runs.append({
                "run_id": r["run_id"],
                "timestamp": r["timestamp"],
                "project_path": r["project_path"],
                "status": r["status"],
                "nodes": r["nodes"],
                "edges": r["edges"],
                "metadata": meta
            })
        return runs
    finally:
        conn.close()


def record_detected_library(db_path: str | Path, run_id: str, library_name: str, version: str | None, ecosystem: str | None) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO detected_libraries (run_id, library_name, version, ecosystem) VALUES (?, ?, ?, ?)",
            (run_id, library_name, version, ecosystem)
        )
        conn.commit()
    finally:
        conn.close()


def record_support_pack(db_path: str | Path, pack_id: str, ecosystem: str, library_name: str, version: str | None, path: str, metadata_dict: dict | None = None) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        meta_str = json.dumps(metadata_dict) if metadata_dict is not None else None
        cursor.execute(
            "INSERT OR REPLACE INTO support_packs (pack_id, ecosystem, library_name, version, path, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (pack_id, ecosystem, library_name, version, path, meta_str)
        )
        conn.commit()
    finally:
        conn.close()
