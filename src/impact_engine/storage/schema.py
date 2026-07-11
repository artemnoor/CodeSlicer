"""SQLite DB Table Schemas. Stage 12."""

CREATE_ANALYSIS_RUNS = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    project_path TEXT NOT NULL,
    status TEXT NOT NULL,
    nodes INTEGER NOT NULL,
    edges INTEGER NOT NULL,
    metadata TEXT
);
"""

CREATE_DETECTED_LIBRARIES = """
CREATE TABLE IF NOT EXISTS detected_libraries (
    library_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    library_name TEXT NOT NULL,
    version TEXT,
    ecosystem TEXT,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id) ON DELETE CASCADE
);
"""

CREATE_SUPPORT_PACKS = """
CREATE TABLE IF NOT EXISTS support_packs (
    pack_id TEXT PRIMARY KEY,
    ecosystem TEXT NOT NULL,
    library_name TEXT NOT NULL,
    version TEXT,
    path TEXT NOT NULL,
    metadata TEXT
);
"""

CREATE_RESEARCH_WORKFLOWS = """
CREATE TABLE IF NOT EXISTS research_workflows (
    workflow_id TEXT PRIMARY KEY,
    library_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_path TEXT
);
"""
