import pytest
import sqlite3
from pathlib import Path
from impact_engine.storage.db import (
    init_db,
    record_analysis_run,
    list_analysis_runs,
    record_detected_library,
    record_support_pack
)


def test_db_operations(tmp_path):
    db_file = tmp_path / "test.sqlite"
    
    # 1. Initialize DB (idempotent check)
    init_db(db_file)
    assert db_file.exists()
    
    init_db(db_file)  # Second run should not fail
    
    # Check tables
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cursor.fetchall()}
    assert "analysis_runs" in tables
    assert "detected_libraries" in tables
    assert "support_packs" in tables
    assert "research_workflows" in tables
    conn.close()
    
    # 2. Record and List analysis runs
    record_analysis_run(
        db_path=db_file,
        run_id="run-1",
        project_path="/mock/path",
        status="ok",
        nodes=10,
        edges=5,
        metadata_dict={"test": "val"}
    )
    
    runs = list_analysis_runs(db_file)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run-1"
    assert runs[0]["project_path"] == "/mock/path"
    assert runs[0]["nodes"] == 10
    assert runs[0]["edges"] == 5
    assert runs[0]["metadata"] == {"test": "val"}
    
    # 3. Record detected library
    record_detected_library(
        db_path=db_file,
        run_id="run-1",
        library_name="requests",
        version="2.28.0",
        ecosystem="python"
    )
    
    # Verify in DB
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM detected_libraries")
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "run-1" # run_id
    assert rows[0][2] == "requests" # library_name
    assert rows[0][3] == "2.28.0" # version
    assert rows[0][4] == "python" # ecosystem
    conn.close()
    
    # 4. Record support pack
    record_support_pack(
        db_path=db_file,
        pack_id="python::requests",
        ecosystem="python",
        library_name="requests",
        version=">=2.0.0",
        path="/packs/requests/support_pack.json",
        metadata_dict={"status": "verified"}
    )
    
    # Verify in DB
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM support_packs")
    sp_rows = cursor.fetchall()
    assert len(sp_rows) == 1
    assert sp_rows[0][0] == "python::requests"
    assert sp_rows[0][1] == "python"
    assert sp_rows[0][4] == "/packs/requests/support_pack.json"
    conn.close()
