from project_semantics_hygiene import FileRoleClassifier, GraphAnnotator, ImpactFilter, ProjectFile, group_nodes_by_semantic_role


def _graph_and_annotations():
    files = [
        ProjectFile("backend/routes/accounts.py"),
        ProjectFile("backend/services/account_service.py"),
        ProjectFile("backend/repositories/account_repository.py"),
        ProjectFile("frontend/src/components/Account.tsx"),
        ProjectFile("tests/test_accounts.py"),
        ProjectFile("contracts/openapi.json"),
        ProjectFile("generated/client.generated.ts"),
        ProjectFile("pyproject.toml"),
        ProjectFile("docs/readme.md"),
        ProjectFile("backend/services/dead_service.py"),
    ]
    graph = {
        "nodes": [
            {"id": "route", "kind": "ROUTE", "name": "GET /api/accounts/{id}", "properties": {"file": "backend/routes/accounts.py"}},
            {"id": "service", "kind": "CLASS", "name": "AccountService", "properties": {"file": "backend/services/account_service.py"}},
            {"id": "repo", "kind": "CLASS", "name": "AccountRepository", "properties": {"file": "backend/repositories/account_repository.py"}},
            {"id": "frontend", "kind": "COMPONENT", "name": "AccountCard", "properties": {"file": "frontend/src/components/Account.tsx"}},
            {"id": "test", "kind": "FUNCTION", "name": "test_accounts", "properties": {"file": "tests/test_accounts.py"}},
            {"id": "contract", "kind": "SCHEMA", "name": "OpenAPI", "properties": {"file": "contracts/openapi.json"}},
            {"id": "generated", "kind": "CLASS", "name": "GeneratedClient", "properties": {"file": "generated/client.generated.ts"}},
            {"id": "config", "kind": "FILE", "name": "pyproject", "properties": {"file": "pyproject.toml"}},
            {"id": "docs", "kind": "FILE", "name": "README", "properties": {"file": "docs/readme.md"}},
            {"id": "dead", "kind": "CLASS", "name": "DeadService", "properties": {"file": "backend/services/dead_service.py"}},
            {"id": "dep", "kind": "EXTERNAL", "name": "orbitlane", "properties": {}},
        ],
        "edges": [],
    }
    classifications = FileRoleClassifier().classify_many(files)
    annotations, _ = GraphAnnotator().annotate_graph(graph, classifications)
    return graph, annotations


def test_filter_modes():
    graph, annotations = _graph_and_annotations()
    f = ImpactFilter()
    assert {n["id"] for n in f.filter_nodes(graph["nodes"], annotations, "main")} >= {"route", "service", "repo", "frontend", "test"}
    assert "generated" not in {n["id"] for n in f.filter_nodes(graph["nodes"], annotations, "main")}
    assert "dead" not in {n["id"] for n in f.filter_nodes(graph["nodes"], annotations, "main")}
    assert {n["id"] for n in f.filter_nodes(graph["nodes"], annotations, "runtime")} >= {"route", "service", "repo", "frontend"}
    assert "test" not in {n["id"] for n in f.filter_nodes(graph["nodes"], annotations, "runtime")}
    assert {n["id"] for n in f.filter_nodes(graph["nodes"], annotations, "tests")} == {"test"}
    assert len(f.filter_nodes(graph["nodes"], annotations, "all")) == len(graph["nodes"])
    assert {n["id"] for n in f.filter_nodes(graph["nodes"], annotations, "noise")} == {"generated", "dead"}


def test_grouping_detects_semantic_roles():
    graph, annotations = _graph_and_annotations()
    groups = group_nodes_by_semantic_role(graph["nodes"], annotations)
    assert [n["id"] for n in groups["routes"]] == ["route"]
    assert "service" in [n["id"] for n in groups["services"]]
    assert "dead" in [n["id"] for n in groups["services"]]  # still semantically a service, but filterable as noise
    assert [n["id"] for n in groups["repositories"]] == ["repo"]
    assert [n["id"] for n in groups["tests"]] == ["test"]
    assert [n["id"] for n in groups["frontend"]] == ["frontend"]
    assert [n["id"] for n in groups["contracts"]] == ["contract"]
    assert [n["id"] for n in groups["generated"]] == ["generated"]
    assert [n["id"] for n in groups["configs"]] == ["config"]
    assert [n["id"] for n in groups["docs"]] == ["docs"]
    assert [n["id"] for n in groups["external_libraries"]] == ["dep"]
