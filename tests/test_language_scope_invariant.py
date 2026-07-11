from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution_coverage import _node_language


def test_python_callsite_carries_file_and_line_and_never_unknown_language(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("def run(repo):\n    return repo.save()\n", encoding="utf-8")
    graph = extract_project(tmp_path)
    calls = [node for node in graph.nodes if node.kind == "CALL_EXPR"]
    assert calls
    assert calls[0].properties["file"] == "service.py"
    assert calls[0].properties["line"] == 2
    assert _node_language(calls[0]) == "python"
