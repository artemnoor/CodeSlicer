import json

from impact_engine.scope import build_scan_plan, iter_project_files, write_scan_plan


def test_scope_prunes_dependency_trees_and_nested_git_repositories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}\n", encoding="utf-8")
    (tmp_path / "nested" / ".git").mkdir(parents=True)
    (tmp_path / "nested" / "src.py").write_text("print('excluded')\n", encoding="utf-8")

    files = {path.relative_to(tmp_path).as_posix() for path in iter_project_files(tmp_path)}
    plan = build_scan_plan(tmp_path)

    assert "src/main.py" in files
    assert "node_modules/pkg/index.js" not in files
    assert "nested/src.py" not in files
    assert "node_modules" in plan["excluded_directories"]
    assert "nested" in plan["excluded_directories"]


def test_scan_plan_is_reusable(tmp_path):
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    path = write_scan_plan(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["schema_version"] == "impact_engine.scan_plan.v1"
    assert data["included_files"] == 1
