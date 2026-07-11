from project_semantics_hygiene import DependencyClassifier, DependencyKind


def test_uuid_python_stdlib_requires_no_research():
    dc = DependencyClassifier().classify_dependency("uuid", "python")
    assert dc.kind is DependencyKind.STDLIB
    assert dc.requires_research is False


def test_pydantic_known_common_third_party():
    dc = DependencyClassifier().classify_dependency("pydantic", "python")
    assert dc.kind is DependencyKind.KNOWN_COMMON_THIRD_PARTY
    assert dc.requires_research is False


def test_python_common_dependencies_are_case_insensitive():
    classifier = DependencyClassifier()
    assert classifier.classify_dependency("SQLAlchemy", "python").kind is DependencyKind.KNOWN_COMMON_THIRD_PARTY
    assert classifier.classify_dependency("uvicorn", "python").kind is DependencyKind.KNOWN_COMMON_THIRD_PARTY


def test_fastapi_routing_maps_top_level():
    dc = DependencyClassifier().classify_dependency("fastapi.routing", "python")
    assert dc.kind is DependencyKind.KNOWN_COMMON_THIRD_PARTY
    assert "fastapi" in dc.reasons[0]


def test_local_module_wins_over_third_party():
    dc = DependencyClassifier().classify_dependency("fastapi.routing", "python", local_modules={"fastapi"})
    assert dc.kind is DependencyKind.LOCAL
    assert dc.local is True


def test_declared_dependency_wins_over_unknown():
    dc = DependencyClassifier().classify_dependency("orbitlane.client", "python", declared_dependencies={"orbitlane"})
    assert dc.kind is DependencyKind.DECLARED_THIRD_PARTY
    assert dc.declared is True
    assert dc.requires_research is False


def test_dev_and_type_only():
    classifier = DependencyClassifier()
    assert classifier.classify_dependency("pytest", "python", dev_dependencies={"pytest"}).kind is DependencyKind.DEV_ONLY
    assert classifier.classify_dependency("typing_extensions", "python", type_only=True).kind is DependencyKind.TYPE_ONLY


def test_unknown_dependency_requires_research():
    dc = DependencyClassifier().classify_dependency("orbitlane", "python")
    assert dc.kind is DependencyKind.UNKNOWN_THIRD_PARTY
    assert dc.requires_research is True


def test_npm_scoped_packages():
    dc = DependencyClassifier().classify_dependency("@scope/name/subpath", "typescript", declared_dependencies={"@scope/name"})
    assert dc.kind is DependencyKind.DECLARED_THIRD_PARTY
    assert dc.declared is True


def test_node_builtins():
    dc = DependencyClassifier().classify_dependency("node:fs/promises", "typescript")
    assert dc.kind is DependencyKind.BUILTIN_RUNTIME
    assert dc.requires_research is False


def test_react_not_builtin_known_common():
    dc = DependencyClassifier().classify_dependency("react", "typescript")
    assert dc.kind is DependencyKind.KNOWN_COMMON_THIRD_PARTY


def test_go_stdlib_and_declared_github_module():
    classifier = DependencyClassifier()
    assert classifier.classify_dependency("net/http", "go").kind is DependencyKind.STDLIB
    assert classifier.classify_dependency("net/http/httptest", "go").kind is DependencyKind.STDLIB
    dc = classifier.classify_dependency("github.com/foo/bar/pkg", "go", declared_dependencies={"github.com/foo/bar"})
    assert dc.kind is DependencyKind.DECLARED_THIRD_PARTY


def test_java_stdlib_and_spring_known():
    classifier = DependencyClassifier()
    assert classifier.classify_dependency("java.util.List", "java").kind is DependencyKind.STDLIB
    assert classifier.classify_dependency("org.springframework.web.bind.annotation", "java").kind is DependencyKind.KNOWN_COMMON_THIRD_PARTY
