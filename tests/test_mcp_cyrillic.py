import json
from pathlib import Path
from impact_engine.mcp.server import analyze_project, project_inventory


def test_mcp_cyrillic_paths_support(tmp_path):
    # Create a path with Cyrillic characters
    cyrillic_dir = tmp_path / "ТестовыйПроект"
    cyrillic_dir.mkdir()
    
    # Write a simple python file in it
    py_file = cyrillic_dir / "main.py"
    py_file.write_text("def compute():\n    return 42\n", encoding="utf-8")
    
    # Verify analyze_project can handle it
    out_path = tmp_path / "graph.json"
    res = analyze_project(str(cyrillic_dir), out_path=str(out_path))
    assert res["status"] == "ok"
    assert out_path.exists()
    
    # Verify project_inventory can handle it
    res_inv = project_inventory(str(cyrillic_dir))
    assert res_inv["status"] == "ok"
    assert "python" in res_inv["inventory"]["languages"]
