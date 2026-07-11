from project_semantics_hygiene import FileRole, FileRoleClassifier, GraphAnnotator, ProjectFile, Reachability


def _classes():
    files = [
        ProjectFile("src/service.py"),
        ProjectFile("src/generated/client.generated.py"),
        ProjectFile("tests/test_service.py"),
        ProjectFile("src/dead_service.py"),
        ProjectFile("contracts/openapi.json"),
    ]
    return FileRoleClassifier().classify_many(files)


def test_node_annotations_by_file_role_and_tags():
    graph = {
        "nodes": [
            {"id": "runtime", "kind": "CLASS", "name": "Service", "properties": {"file": "src/service.py"}},
            {"id": "gen", "kind": "CLASS", "name": "Client", "properties": {"file": "src/generated/client.generated.py"}},
            {"id": "test", "kind": "FUNCTION", "name": "test_service", "properties": {"file": "tests/test_service.py"}},
            {"id": "dead", "kind": "CLASS", "name": "DeadService", "properties": {"file": "src/dead_service.py"}},
            {"id": "route", "kind": "ROUTE", "name": "GET /api/users/{id}", "properties": {"file": "src/service.py"}},
            {"id": "contract", "kind": "SCHEMA", "name": "OpenAPI", "properties": {"file": "contracts/openapi.json"}},
        ],
        "edges": [],
    }
    nodes, _ = GraphAnnotator().annotate_graph(graph, _classes())
    by_id = {n.node_id: n for n in nodes}
    assert by_id["runtime"].reachability is Reachability.RUNTIME
    assert by_id["gen"].reachability is Reachability.GENERATED_ONLY
    assert by_id["test"].reachability is Reachability.TEST_ONLY
    assert by_id["dead"].reachability is Reachability.UNREACHABLE_CANDIDATE
    assert "route" in by_id["route"].tags
    assert "contract" in by_id["contract"].tags
    assert by_id["contract"].file_role is FileRole.CONTRACT


def test_edge_reachability_and_noise_scores():
    graph = {
        "nodes": [
            {"id": "runtime", "kind": "CLASS", "name": "Service", "properties": {"file": "src/service.py"}},
            {"id": "gen", "kind": "CLASS", "name": "Client", "properties": {"file": "src/generated/client.generated.py"}},
            {"id": "test", "kind": "FUNCTION", "name": "test_service", "properties": {"file": "tests/test_service.py"}},
            {"id": "dead", "kind": "CLASS", "name": "DeadService", "properties": {"file": "src/dead_service.py"}},
        ],
        "edges": [
            {"id": "e_runtime", "kind": "CALLS", "from": "runtime", "to": "runtime", "properties": {}},
            {"id": "e_gen", "kind": "CALLS", "from": "runtime", "to": "gen", "properties": {}},
            {"id": "e_test", "kind": "TESTS", "from": "test", "to": "runtime", "properties": {}},
            {"id": "e_dead", "kind": "CALLS", "from": "runtime", "to": "dead", "properties": {}},
        ],
    }
    _, edges = GraphAnnotator().annotate_graph(graph, _classes())
    by_id = {e.edge_id: e for e in edges}
    assert by_id["e_runtime"].reachability is Reachability.RUNTIME
    assert by_id["e_runtime"].noise_score == 0.10
    assert by_id["e_gen"].reachability is Reachability.GENERATED_ONLY
    assert by_id["e_gen"].noise_score == 0.90
    assert by_id["e_test"].reachability is Reachability.TEST_ONLY
    assert by_id["e_test"].noise_score == 0.40
    assert by_id["e_dead"].reachability is Reachability.UNREACHABLE_CANDIDATE
    assert by_id["e_dead"].noise_score == 0.70
