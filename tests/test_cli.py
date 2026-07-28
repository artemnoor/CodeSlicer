import json
from pathlib import Path

from tests.helpers.cli_runner import run_cli

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


# These tests intentionally call impact_engine.cli.main(...) in-process instead
# of spawning python -m impact_engine.cli. The previous subprocess pattern could
# hang only in full-suite order, while test_cli_db passed by itself. In-process
# execution still exercises the CLI parser and command dispatch but leaves no
# child processes, pipes, or pytest capture state behind.


def test_cli_analyze_writes_graph(tmp_path):
    graph_path = tmp_path / "graph.json"

    res = run_cli([
        "--json",
        "analyze",
        str(PROJECT_PATH),
        "--out",
        str(graph_path),
    ], cwd=tmp_path)

    summary = json.loads(res.stdout)
    assert summary["status"] == "ok"
    assert summary["graph_path"] == str(graph_path)
    assert summary["nodes"] > 0
    assert summary["edges"] > 0

    assert graph_path.exists()
    graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    edges = graph_data.get("edges", [])
    main_edge = next(
        (
            e for e in edges
            if e.get("kind") == "CALLS"
            and e.get("from") == "services.OrderService.create_order"
            and e.get("to") == "repositories.OrderRepository.save"
        ),
        None,
    )
    assert main_edge is not None
    assert main_edge["source"] == "INFERRED"
    assert main_edge["confidence"] >= 0.80


def test_cli_default_graph_is_project_local_and_ignores_graphify_outputs(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    generated = project / "graphify-out" / "cache"
    generated.mkdir(parents=True)
    (generated / "noise.py").write_text("def must_not_be_indexed():\n    return 0\n", encoding="utf-8")

    res = run_cli(["--json", "analyze", str(project), "--no-research-requests"], cwd=tmp_path)

    summary = json.loads(res.stdout)
    expected = project / ".impact_engine" / "graph.json"
    assert summary["graph_path"] == str(expected)
    assert expected.is_file()
    assert not (tmp_path / "graph.json").exists()
    inventory = summary["inventory"]
    assert "app.py" in inventory["files"]
    assert not any("graphify-out" in path for path in inventory["files"])


def test_cli_generic_adapter_preflight_and_import(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    artifact = tmp_path / "graph.json"
    artifact.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")

    preflight = run_cli(["--json", "adapters", "preflight", str(project)], cwd=tmp_path)
    assert "graphify" in {item["id"] for item in json.loads(preflight.stdout)["adapters"]}

    imported = run_cli([
        "--json", "adapters", "import", str(project), "graphify", str(artifact.resolve()), "--enable",
    ], cwd=tmp_path)
    payload = json.loads(imported.stdout)
    assert payload["adapter"]["status"] == "ready"


def test_cli_impact_outputs_json(tmp_path):
    graph_path = tmp_path / "graph.json"
    run_cli(["--json", "analyze", str(PROJECT_PATH), "--out", str(graph_path)], cwd=tmp_path)

    res = run_cli([
        "--json",
        "impact",
        "--graph",
        str(graph_path),
        "--target",
        "services.OrderService.create_order",
    ], cwd=tmp_path)

    result = json.loads(res.stdout)
    assert result["target"] == "services.OrderService.create_order"
    assert "upstream" in result
    assert "downstream" in result
    assert "repositories.OrderRepository.save" in result["downstream"]


def test_cli_explain_edge_outputs_evidence(tmp_path):
    graph_path = tmp_path / "graph.json"
    run_cli(["--json", "analyze", str(PROJECT_PATH), "--out", str(graph_path)], cwd=tmp_path)

    res = run_cli([
        "--json",
        "explain-edge",
        "--graph",
        str(graph_path),
        "--from",
        "services.OrderService.create_order",
        "--to",
        "repositories.OrderRepository.save",
        "--kind",
        "CALLS",
    ], cwd=tmp_path)

    result = json.loads(res.stdout)
    assert result["found"] is True
    assert result["edge"]["from"] == "services.OrderService.create_order"
    assert result["edge"]["to"] == "repositories.OrderRepository.save"
    assert result["edge"]["source"] == "INFERRED"
    assert len(result["evidence"]) >= 4


def test_cli_detect_languages(tmp_path):
    res = run_cli(["--json", "detect-languages", str(PROJECT_PATH)], cwd=tmp_path)
    langs = json.loads(res.stdout)
    assert "python" in langs


def test_cli_inventory(tmp_path):
    res = run_cli(["--json", "inventory", str(PROJECT_PATH)], cwd=tmp_path)
    inv = json.loads(res.stdout)
    assert inv["root_path"] is not None
    assert "python" in inv["languages"]
    assert any("container.py" in f for f in inv["files"])


def test_cli_support_packs(tmp_path):
    res = run_cli(["--json", "support-packs", "list"], cwd=tmp_path)
    packs = json.loads(res.stdout)
    assert isinstance(packs, list)


def test_cli_db_sequence_safe(tmp_path):
    db_file = tmp_path / "cli_test.sqlite"

    res = run_cli(["--json", "db", "init", "--path", str(db_file)], cwd=tmp_path)
    out = json.loads(res.stdout)
    assert out["status"] == "ok"
    assert db_file.exists()

    res_runs = run_cli(["--json", "db", "runs", "--path", str(db_file)], cwd=tmp_path)
    runs = json.loads(res_runs.stdout)
    assert isinstance(runs, list)
