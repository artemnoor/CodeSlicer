from __future__ import annotations

from types import SimpleNamespace

from impact_engine.adapters.native import native_profile, run_native_operation
from impact_engine.adapters.graphify_paths import record_graphify_interpreter
from impact_engine.adapters.registry import AdapterRegistry


def test_every_optional_source_exposes_its_full_capability_catalog() -> None:
    expected = {"graphify", "codegraph", "gortex", "joern", "lsp", "scip", "openapi", "asyncapi", "otel", "cyclonedx", "spdx", "sarif"}
    for adapter_id in expected:
        profile = native_profile(adapter_id)
        assert profile["local_only"] is True
        assert profile["network_default"] == "disabled"
        assert profile["capabilities"], adapter_id


def test_native_index_requires_explicit_confirmation(tmp_path) -> None:
    result = run_native_operation(tmp_path, "codegraph", "index")
    assert result["status"] == "confirmation_required"
    assert result["privacy"]["network_used_by_codeslicer"] is False


def test_native_codegraph_query_is_allowlisted_and_never_uses_shell(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("impact_engine.adapters.native.shutil.which", lambda value: "C:/tools/codegraph.exe" if value == "codegraph" else None)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout='{"symbols": []}', stderr="")

    monkeypatch.setattr("impact_engine.adapters.native.subprocess.run", fake_run)
    result = run_native_operation(tmp_path, "codegraph", "impact", confirmed=True, query="src/auth.ts::login")
    assert result["status"] == "completed"
    assert captured["command"] == [
        "C:/tools/codegraph.exe", "impact", "src/auth.ts::login",
        "--path", str(tmp_path.resolve()), "--json",
    ]
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["cwd"] == str(tmp_path)


def test_gortex_query_requires_a_known_native_query_kind(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("impact_engine.adapters.native.shutil.which", lambda value: "C:/tools/gortex.exe" if value == "gortex" else None)
    try:
        run_native_operation(tmp_path, "gortex", "query", confirmed=True, query="unsafe:anything")
    except ValueError as exc:
        assert "Gortex query must start" in str(exc)
    else:
        raise AssertionError("unknown Gortex native command must be rejected")


def test_registry_exposes_native_contract_without_starting_external_tools(tmp_path) -> None:
    from impact_engine.adapters.registry import AdapterRegistry

    item = AdapterRegistry(tmp_path).status("graphify")
    assert item["native"]["mode"] == "native-local-tool"
    assert item["native"]["operations"]
    assert item["network_used"] is False


def test_registry_accepts_only_explicit_existing_native_executable(tmp_path) -> None:
    executable = tmp_path / "codegraph.cmd"
    executable.write_text("@echo off\n", encoding="utf-8")
    registry = AdapterRegistry(tmp_path)
    configured = registry.configure_native_executable("codegraph", executable)
    assert configured["native"]["configured_executable"] == str(executable.resolve())
    assert configured["native"]["available"] is True
    try:
        registry.configure_native_executable("codegraph", tmp_path / "missing.cmd")
    except ValueError as exc:
        assert "existing absolute" in str(exc)
    else:
        raise AssertionError("missing executable must be rejected")


def test_native_contract_validator_uses_only_an_absolute_local_spec(tmp_path, monkeypatch) -> None:
    spec = tmp_path / "openapi.yaml"
    spec.write_text("openapi: 3.0.3\ninfo: {title: local, version: 1}\npaths: {}\n", encoding="utf-8")
    monkeypatch.setattr("impact_engine.adapters.native.shutil.which", lambda value: "C:/tools/redocly.cmd" if value in {"redocly", "redocly.cmd"} else None)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="valid", stderr="")

    monkeypatch.setattr("impact_engine.adapters.native.subprocess.run", fake_run)
    result = run_native_operation(tmp_path, "openapi", "validate", confirmed=True, query=str(spec.resolve()))
    assert result["status"] == "completed"
    assert calls[0][0] == ["C:/tools/redocly.cmd", "lint", str(spec.resolve())]
    assert calls[0][1]["shell"] is False
    try:
        run_native_operation(tmp_path, "openapi", "validate", confirmed=True, query="https://example.test/openapi.yaml")
    except ValueError as exc:
        assert "absolute local" in str(exc)
    else:
        raise AssertionError("remote contract source must be rejected")


def test_graphify_renderer_records_the_interpreter_from_its_own_environment(tmp_path) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    executable = scripts / "graphify.exe"
    interpreter = scripts / "python.exe"
    executable.write_text("placeholder", encoding="utf-8")
    interpreter.write_text("placeholder", encoding="utf-8")
    graph = tmp_path / "out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text("{}", encoding="utf-8")

    recorded = record_graphify_interpreter(graph, executable)
    assert recorded is not None
    assert recorded.read_text(encoding="utf-8").strip() == str(interpreter.resolve())


def test_graphify_index_creates_viewer_once_and_reports_its_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("impact_engine.adapters.native.shutil.which", lambda value: "C:/tools/graphify.exe" if value == "graphify" else None)
    monkeypatch.setattr("impact_engine.adapters.native.subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""))
    calls = []
    viewer = tmp_path / ".codeslicer" / "artifacts" / "graphify" / "graphify-out" / ".codeslicer_graphify_viewer.html"
    monkeypatch.setattr("impact_engine.adapters.native.cache_graphify_viewer", lambda project: calls.append(project) or viewer)
    result = run_native_operation(tmp_path, "graphify", "index", confirmed=True)
    assert calls == [tmp_path]
    assert result["viewer_status"] == "ready"
    assert result["viewer_artifact"] == str(viewer)
