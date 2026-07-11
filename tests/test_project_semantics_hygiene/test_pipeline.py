import json

from project_semantics_hygiene import DependencyKind, HygienePipeline, ImpactFilter, ProjectFile, Reachability, RouteNormalizer
from project_semantics_hygiene.serialization import from_json_report, to_json


def test_end_to_end_polyglot_mini_project():
    files = [
        ProjectFile("backend/routes/accounts.py"),
        ProjectFile("backend/services/account_service.py"),
        ProjectFile("backend/repositories/account_repository.py"),
        ProjectFile("frontend/src/components/AccountView.tsx"),
        ProjectFile("frontend/src/__generated__/client.generated.ts", "// Code generated. DO NOT EDIT\nexport {}"),
        ProjectFile("tests/test_accounts.py"),
        ProjectFile("contracts/openapi.json"),
        ProjectFile("backend/services/dead_account_service.py"),
    ]
    dependencies = [
        ("uuid", "python"),
        ("pydantic", "python"),
        ("orbitlane", "python"),
        ("react", "typescript"),
        ("fs", "typescript"),
        ("github.com/unknown/thing", "go"),
        ("java.util.List", "java"),
    ]
    routes = [
        ("GET", "/api/admin/accounts/{account_id}", "backend"),
        ("get", "`/api/admin/accounts/${id}`", "frontend"),
    ]
    graph = {
        "nodes": [
            {"id": "route:accounts", "kind": "ROUTE", "name": "GET /api/admin/accounts/{account_id}", "properties": {"file": "backend/routes/accounts.py"}},
            {"id": "svc:AccountService", "kind": "CLASS", "name": "AccountService", "properties": {"file": "backend/services/account_service.py"}},
            {"id": "repo:AccountRepository", "kind": "CLASS", "name": "AccountRepository", "properties": {"file": "backend/repositories/account_repository.py"}},
            {"id": "ui:AccountView", "kind": "COMPONENT", "name": "AccountView", "properties": {"file": "frontend/src/components/AccountView.tsx"}},
            {"id": "gen:client", "kind": "CLASS", "name": "GeneratedClient", "properties": {"file": "frontend/src/__generated__/client.generated.ts"}},
            {"id": "test:accounts", "kind": "FUNCTION", "name": "test_accounts", "properties": {"file": "tests/test_accounts.py"}},
            {"id": "contract:openapi", "kind": "SCHEMA", "name": "OpenAPI", "properties": {"file": "contracts/openapi.json"}},
            {"id": "dead:AccountService", "kind": "CLASS", "name": "DeadAccountService", "properties": {"file": "backend/services/dead_account_service.py"}},
        ],
        "edges": [
            {"id": "e1", "kind": "CALLS", "from": "route:accounts", "to": "svc:AccountService", "properties": {}},
            {"id": "e2", "kind": "CALLS", "from": "svc:AccountService", "to": "repo:AccountRepository", "properties": {}},
            {"id": "e3", "kind": "CALLS", "from": "ui:AccountView", "to": "route:accounts", "properties": {}},
            {"id": "e4", "kind": "CALLS", "from": "ui:AccountView", "to": "gen:client", "properties": {}},
            {"id": "e5", "kind": "CALLS", "from": "route:accounts", "to": "dead:AccountService", "properties": {}},
            {"id": "e6", "kind": "TESTS", "from": "test:accounts", "to": "route:accounts", "properties": {}},
        ],
    }

    report = HygienePipeline().run(
        files=files,
        dependencies=dependencies,
        declared_dependencies={"typescript": {"react"}},
        graph=graph,
        routes=routes,
    )

    deps = {d.name: d for d in report.dependencies}
    assert deps["uuid"].kind is DependencyKind.STDLIB
    assert deps["pydantic"].kind is DependencyKind.KNOWN_COMMON_THIRD_PARTY
    assert deps["orbitlane"].kind is DependencyKind.UNKNOWN_THIRD_PARTY
    assert deps["orbitlane"].requires_research is True
    assert deps["react"].kind is DependencyKind.DECLARED_THIRD_PARTY
    assert deps["fs"].kind is DependencyKind.BUILTIN_RUNTIME
    assert deps["java.util.List"].kind is DependencyKind.STDLIB

    main_nodes = ImpactFilter().filter_nodes(graph["nodes"], report.node_annotations, "main")
    main_ids = {n["id"] for n in main_nodes}
    assert "gen:client" not in main_ids
    assert "dead:AccountService" not in main_ids
    assert "test:accounts" in main_ids

    rn = RouteNormalizer()
    assert rn.equivalent(report.routes[0].original, report.routes[1].original)
    assert report.summary["files.total"] == 8
    assert report.summary["files.generated"] == 1
    assert report.summary["files.tests"] == 1
    assert report.summary["files.contracts"] == 1
    assert report.summary["files.dead_candidates"] == 1
    assert report.summary["dependencies.requires_research"] == 2
    assert report.summary["nodes.GENERATED_ONLY"] == 1
    assert report.summary["nodes.UNREACHABLE_CANDIDATE"] == 1

    # JSON is safe: no enum objects leak into serialized dict/text.
    raw = report.to_dict()
    assert isinstance(raw["files"][0]["role"], str)
    text = to_json(report)
    assert "FileRole" not in text and "DependencyKind" not in text and "Reachability" not in text
    restored = from_json_report(text)
    assert restored.summary == report.summary
    json.loads(text)
