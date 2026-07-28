"""Local-only native tool contracts for optional CodeSlicer sources.

This module deliberately does *not* reimplement Graphify, CodeGraph, Gortex,
Joern, language servers, or supply-chain standards.  It gives the local hub a
safe, versioned way to discover an installed upstream tool, expose its real
capabilities, and run a small allowlisted set of documented commands after an
explicit user confirmation.  The upstream tool continues to own its complete
graph and its own cache.

No shell is used.  Project paths and user arguments are passed as individual
subprocess arguments, output is bounded, and an external process is never
started implicitly by analysis, review, watch, or UI refresh.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any


MAX_OUTPUT_CHARS = 24_000
MAX_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class NativeOperation:
    id: str
    title: str
    description: str
    kind: str  # probe, index, query, service, import
    requires_confirmation: bool = True
    requires_query: bool = False
    supported_query_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class NativeTool:
    adapter_id: str
    executables: tuple[str, ...]
    upstream_url: str
    license_note: str
    capabilities: tuple[str, ...]
    operations: tuple[NativeOperation, ...]


_TOOLS: dict[str, NativeTool] = {
    "graphify": NativeTool(
        "graphify", ("graphify",), "https://github.com/Graphify-Labs/graphify", "Upstream license applies.",
        ("code/docs/SQL/config graph", "communities and architecture hotspots", "rationale/ADR links", "MCP query_graph, shortest_path and PR triage", "wiki, Obsidian, SVG and GraphML exports"),
        (
            NativeOperation("probe", "Проверить Graphify", "Показывает локальную версию; исходники не анализируются.", "probe", False),
            NativeOperation("index", "Построить architecture graph", "Запускает Graphify code-only extraction в graphify-out/.", "index"),
            NativeOperation("refresh", "Обновить изменённые файлы", "Запускает native incremental update Graphify.", "index"),
            NativeOperation("query", "Нативный Graphify query", "Ищет путь или архитектурный контекст в полном Graphify graph.", "query", True, True),
        ),
    ),
    "codegraph": NativeTool(
        "codegraph", ("codegraph",), "https://github.com/colbymchenry/codegraph", "MIT upstream; use the installed version's terms.",
        ("persistent local SQLite semantic graph", "native file watcher and incremental sync", "symbols, callers, callees and dynamic-dispatch traces", "framework routes and affected tests", "MCP context/explore/impact queries"),
        (
            NativeOperation("probe", "Проверить CodeGraph", "Показывает локальную версию; проект не изменяется.", "probe", False),
            NativeOperation("index", "Индексировать проект", "Создаёт или обновляет локальный .codegraph index.", "index"),
            NativeOperation("sync", "Синхронизировать изменения", "Выполняет native incremental sync CodeGraph.", "index"),
            NativeOperation("status", "Статус native index", "Показывает состояние полного CodeGraph index.", "query", False),
            NativeOperation("query", "Найти символы", "Нативный поиск в SQLite graph CodeGraph.", "query", True, True),
            NativeOperation("context", "Получить task context", "Возвращает собранный CodeGraph контекст для задачи.", "query", True, True),
            NativeOperation("impact", "Проверить влияние символа", "Выполняет native impact traversal CodeGraph.", "query", True, True),
            NativeOperation("callers", "Найти callers", "Выполняет native caller query CodeGraph.", "query", True, True),
            NativeOperation("callees", "Найти callees", "Выполняет native callee query CodeGraph.", "query", True, True),
            NativeOperation("affected", "Найти затронутые тесты", "Выполняет native affected-test query CodeGraph.", "query", True, True),
        ),
    ),
    "gortex": NativeTool(
        "gortex", ("gortex",), "https://github.com/zzet/gortex", "Source-available license may restrict commercial bundling or competing products; do not vendor it without review.",
        ("multi-repository workspace graph", "communities and execution processes", "cross-repository contracts", "dead code, cycles, hotspots and index health", "MCP/API context, tests and change verification"),
        (
            NativeOperation("probe", "Проверить Gortex", "Показывает локальную версию; проект не изменяется.", "probe", False),
            NativeOperation("index", "Индексировать проект", "Запускает native Gortex index для выбранного локального проекта.", "index"),
            NativeOperation("status", "Статус native graph", "Показывает состояние Gortex workspace/index.", "query", False),
            NativeOperation("query", "Нативный graph query", "Поддерживает symbol, deps, dependents, callers, calls, implementations, usages и stats.", "query", True, True, ("symbol", "deps", "dependents", "callers", "calls", "implementations", "usages", "stats")),
        ),
    ),
    "joern": NativeTool(
        "joern", ("joern-scan", "joern"), "https://github.com/joernio/joern", "Apache-2.0 upstream; CPG construction can be resource-heavy.",
        ("code property graph AST/CFG/PDG", "CPGQL data-flow queries", "source-to-sink paths and dangerous calls", "QueryDB recipes", "source, bytecode and binary analysis"),
        (
            NativeOperation("probe", "Проверить Joern", "Показывает доступные встроенные QueryDB recipes; проект не изменяется.", "probe", False),
            NativeOperation("recipes", "Список security recipes", "Выводит список доступных Joern QueryDB queries.", "query", False),
        ),
    ),
    "openapi": NativeTool(
        "openapi", ("redocly", "redocly.cmd"), "https://github.com/Redocly/redocly-cli", "Redocly CLI is optional and runs only from an explicit local executable.",
        ("OpenAPI lint against the upstream ruleset", "bundle a local multi-file contract", "validate before importing into the contracts graph"),
        (
            NativeOperation("probe", "Проверить Redocly", "Показывает локальную версию validator; контракт не читается.", "probe", False),
            NativeOperation("validate", "Проверить OpenAPI", "Проверяет выбранный локальный .json/.yaml контракт через Redocly.", "query", True, True),
            NativeOperation("bundle", "Собрать OpenAPI", "Собирает локальный multi-file контракт в .codeslicer/generated/openapi/.", "index", True, True),
        ),
    ),
    "asyncapi": NativeTool(
        "asyncapi", ("asyncapi", "asyncapi.cmd"), "https://github.com/asyncapi/cli", "AsyncAPI CLI is optional and runs only from an explicit local executable.",
        ("AsyncAPI validation", "local HTML/documentation generation", "validate before importing into the contracts graph"),
        (
            NativeOperation("probe", "Проверить AsyncAPI CLI", "Показывает локальную версию CLI; контракт не читается.", "probe", False),
            NativeOperation("validate", "Проверить AsyncAPI", "Проверяет выбранный локальный .json/.yaml контракт.", "query", True, True),
        ),
    ),
    "scip": NativeTool(
        "scip", ("scip-typescript", "scip-typescript.cmd", "scip-python", "scip-python.cmd"), "https://github.com/sourcegraph/scip", "Choose an installed language indexer explicitly; generated index remains local.",
        ("offline compiler/indexer symbol facts", "stable symbol occurrences", "import a generated .scip index as a separate symbols graph"),
        (
            NativeOperation("probe", "Проверить SCIP indexer", "Показывает версию обнаруженного language-specific indexer.", "probe", False),
            NativeOperation("index", "Построить SCIP index", "Строит .codeslicer/generated/scip/index.scip для TypeScript indexer.", "index"),
        ),
    ),
    "cyclonedx": NativeTool(
        "cyclonedx", ("cyclonedx-py", "cyclonedx-py.exe", "cyclonedx-npm", "cyclonedx-npm.cmd"), "https://github.com/CycloneDX", "Generator selection follows the locally installed ecosystem-specific CLI.",
        ("generate a local SBOM", "dependencies, licenses, VEX/VDR when reported", "import a generated CycloneDX JSON security graph"),
        (
            NativeOperation("probe", "Проверить SBOM generator", "Показывает версию локального CycloneDX generator.", "probe", False),
            NativeOperation("generate", "Создать CycloneDX SBOM", "Генерирует JSON SBOM в .codeslicer/generated/cyclonedx/.", "index"),
        ),
    ),
    "spdx": NativeTool(
        "spdx", ("syft", "syft.exe"), "https://github.com/anchore/syft", "Syft is an optional local SBOM generator.",
        ("generate SPDX JSON SBOM", "packages and dependency evidence", "import an SPDX security graph"),
        (
            NativeOperation("probe", "Проверить Syft", "Показывает версию локального Syft.", "probe", False),
            NativeOperation("generate", "Создать SPDX SBOM", "Генерирует SPDX JSON в .codeslicer/generated/spdx/.", "index"),
        ),
    ),
    "sarif": NativeTool(
        "sarif", ("semgrep", "semgrep.exe"), "https://github.com/semgrep/semgrep", "Semgrep is optional; CodeSlicer never uses remote rules automatically.",
        ("run a user-supplied local ruleset", "generate SARIF", "import findings into the separate security graph"),
        (
            NativeOperation("probe", "Проверить Semgrep", "Показывает версию локального scanner.", "probe", False),
            NativeOperation("scan", "Создать SARIF", "Запускает Semgrep только с указанным абсолютным путём к локальному rules file.", "query", True, True),
        ),
    ),
}


_STANDARD_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "lsp": ("definitions, references and implementations", "workspace/document symbols", "server-advertised semantic capabilities", "live editor semantic state when explicitly configured"),
    "scip": ("compiler/indexer semantic occurrences", "stable symbols and cross-file references", "language-specific indexer lifecycle", "offline semantic navigation"),
    "openapi": ("operations, schemas and routes", "links, callbacks, webhooks and security schemes", "contract diff and API test coverage"),
    "asyncapi": ("channels, operations and messages", "producer/consumer topology", "reply, correlation and transport bindings"),
    "otel": ("traces, spans and links", "HTTP, database and messaging runtime evidence", "metrics/log correlation when exact trace context exists"),
    "cyclonedx": ("SBOM/SaaSBOM/HBOM/AI-BOM", "components, dependencies, VEX/VDR and attestations", "license and dependency-upgrade impact"),
    "spdx": ("software/files/snippets and licenses", "provenance and build/security profiles", "SPDX 3 AI and dataset references"),
    "sarif": ("rules and findings", "locations, related locations and code flows", "baselines, fixes and multi-scanner provenance"),
}


def _tool(adapter_id: str) -> NativeTool | None:
    return _TOOLS.get(adapter_id)


def _configured_executable(value: str | Path | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file():
        return None
    return str(path.resolve())


def _platform_status(adapter_id: str) -> dict[str, str]:
    if adapter_id == "gortex" and platform.system().lower() == "windows":
        return {
            "status": "unsupported_upstream",
            "message": "Gortex upstream currently publishes Linux/macOS builds only. Configure a local WSL wrapper after installing Gortex inside WSL; CodeSlicer will not pretend that a Windows source build is supported.",
        }
    if adapter_id == "joern":
        return {
            "status": "requires_jdk21",
            "message": "Joern upstream requires JDK 21. A local Windows distribution can run without Docker when its .bat executable is configured with JDK 21.",
        }
    return {"status": "supported", "message": "Supported when a local executable is available."}


def _joern_java_home() -> str | None:
    """Find a local JDK 21 without changing the user's global Java setup."""
    configured = Path(os.environ.get("JAVA_HOME", ""))
    if configured.is_dir() and (configured / "bin" / ("java.exe" if os.name == "nt" else "java")).is_file() and "21" in configured.name:
        return str(configured.resolve())
    if os.name == "nt":
        root = Path("C:/Program Files/Microsoft")
        for candidate in sorted(root.glob("jdk-21*"), reverse=True):
            if (candidate / "bin" / "java.exe").is_file():
                return str(candidate.resolve())
    return None


def native_profile(adapter_id: str, configured_executable: str | Path | None = None) -> dict[str, Any]:
    """Return a UI/API-safe complete capability catalogue for one adapter."""
    tool = _tool(adapter_id)
    if tool is None:
        return {
            "mode": "artifact-or-protocol",
            "upstream_url": None,
            "capabilities": list(_STANDARD_CAPABILITIES.get(adapter_id, ())),
            "operations": [],
            "discovered_executable": None,
            "available": False,
            "network_default": "disabled",
            "local_only": True,
        }
    configured = _configured_executable(configured_executable)
    executable = configured or next((resolved for candidate in tool.executables if (resolved := shutil.which(candidate))), None)
    platform_info = _platform_status(adapter_id)
    return {
        "mode": "native-local-tool",
        "upstream_url": tool.upstream_url,
        "license_note": tool.license_note,
        "capabilities": list(tool.capabilities),
        "operations": [
            {
                "id": operation.id, "title": operation.title, "description": operation.description,
                "kind": operation.kind, "requires_confirmation": operation.requires_confirmation,
                "requires_query": operation.requires_query,
                "supported_query_kinds": list(operation.supported_query_kinds),
            }
            for operation in tool.operations
        ],
        "discovered_executable": executable,
        "configured_executable": configured,
        "available": bool(executable),
        "platform": platform_info,
        "runtime": {"java_home": _joern_java_home(), "required": "JDK 21"} if adapter_id == "joern" else None,
        "network_default": "disabled",
        "local_only": True,
    }


def _operation(adapter_id: str, operation_id: str) -> NativeOperation:
    tool = _tool(adapter_id)
    if tool is None:
        raise ValueError(f"{adapter_id} is an artifact/protocol source and has no bundled native command contract")
    for operation in tool.operations:
        if operation.id == operation_id:
            return operation
    raise ValueError(f"Unknown native operation {operation_id!r} for {adapter_id}")


def _local_contract_path(value: str, adapter_id: str) -> Path:
    source = Path(value).expanduser()
    if not source.is_absolute() or not source.is_file() or source.suffix.lower() not in {".json", ".yaml", ".yml"}:
        raise ValueError(f"{adapter_id} requires an existing absolute local .json/.yaml/.yml path")
    return source.resolve()


def _generated_artifact(project: Path, adapter_id: str, filename: str) -> Path:
    target = project / ".codeslicer" / "generated" / adapter_id / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _command(adapter_id: str, operation_id: str, project: Path, query: str, configured_executable: str | Path | None = None) -> list[str]:
    profile = native_profile(adapter_id, configured_executable)
    executable = profile.get("discovered_executable")
    if not executable:
        raise FileNotFoundError(f"No local executable for {adapter_id}; install it separately or configure a local artifact")
    if adapter_id == "graphify":
        if operation_id == "probe": return [executable, "--version"]
        if operation_id == "index": return [executable, "extract", str(project), "--code-only"]
        if operation_id == "refresh": return [executable, str(project), "--update"]
        if operation_id == "query": return [executable, "query", query, "--graph", str(project / "graphify-out" / "graph.json")]
    if adapter_id == "codegraph":
        if operation_id == "probe": return [executable, "--version"]
        # CodeGraph's documented first-run entry point is `init`, which also
        # builds the first index.  `index` deliberately refuses a project that
        # has not been initialised yet, so using it here made the UI's primary
        # action fail on every clean checkout.
        if operation_id == "index": return [executable, "init", str(project)]
        if operation_id == "sync": return [executable, "sync", str(project)]
        if operation_id == "status": return [executable, "status", str(project)]
        if operation_id == "query": return [executable, "query", query, "--path", str(project), "--json"]
        # The current upstream CLI calls its task-oriented context command
        # `explore`; there is no `context --format json` command.
        if operation_id == "context": return [executable, "explore", query, "--path", str(project)]
        if operation_id in {"impact", "callers", "callees"}:
            return [executable, operation_id, query, "--path", str(project), "--json"]
        if operation_id == "affected": return [executable, "affected", query, "--path", str(project), "--json"]
    if adapter_id == "gortex":
        if operation_id == "probe": return [executable, "version"]
        if operation_id == "index": return [executable, "index", str(project)]
        if operation_id == "status": return [executable, "status", "--json"]
        if operation_id == "query":
            query_kind, _, query_value = query.partition(":")
            if query_kind not in _operation(adapter_id, operation_id).supported_query_kinds:
                raise ValueError("Gortex query must start with one of: symbol:, deps:, dependents:, callers:, calls:, implementations:, usages:, stats:")
            command = [executable, "query", query_kind]
            if query_kind != "stats":
                if not query_value:
                    raise ValueError(f"Gortex {query_kind} query requires a value after ':'.")
                command.append(query_value)
            return [*command, "--format", "json"]
    if adapter_id == "joern":
        if operation_id in {"probe", "recipes"}:
            return [executable, "--list-query-names"]
    if adapter_id == "openapi":
        if operation_id == "probe": return [executable, "--version"]
        source = _local_contract_path(query, adapter_id)
        if operation_id == "validate": return [executable, "lint", str(source)]
        if operation_id == "bundle": return [executable, "bundle", str(source), "--output", str(_generated_artifact(project, adapter_id, "openapi.bundle.yaml"))]
    if adapter_id == "asyncapi":
        if operation_id == "probe": return [executable, "--version"]
        source = _local_contract_path(query, adapter_id)
        if operation_id == "validate": return [executable, "validate", str(source)]
    if adapter_id == "scip":
        if operation_id == "probe": return [executable, "--version"]
        if operation_id == "index":
            if "typescript" not in Path(executable).name.lower():
                raise ValueError("SCIP native index currently supports the configured scip-typescript executable; configure it explicitly for a TypeScript project")
            return [executable, "index", "--cwd", str(project), "--infer-tsconfig", "--output", str(_generated_artifact(project, adapter_id, "index.scip")), "--no-progress-bar"]
    if adapter_id == "cyclonedx":
        if operation_id == "probe": return [executable, "--version"]
        if operation_id == "generate":
            output = _generated_artifact(project, adapter_id, "bom.json")
            name = Path(executable).name.lower()
            if "cyclonedx-py" in name:
                requirements = next((path for path in (project / "requirements.txt", project / "requirements-dev.txt") if path.is_file()), None)
                if requirements:
                    return [executable, "requirements", str(requirements), "--of", "JSON", "--output-file", str(output)]
                return [executable, "environment", "--of", "JSON", "--output-file", str(output)]
            if "cyclonedx-npm" in name:
                return [executable, "--output-file", str(output)]
            raise ValueError("Configured CycloneDX executable is not a supported cyclonedx-py or cyclonedx-npm generator")
    if adapter_id == "spdx":
        if operation_id == "probe": return [executable, "version"]
        if operation_id == "generate":
            output = _generated_artifact(project, adapter_id, "sbom.spdx.json")
            return [executable, f"dir:{project}", "--output", f"spdx-json={output}"]
    if adapter_id == "sarif":
        if operation_id == "probe": return [executable, "--version"]
        if operation_id == "scan":
            rules = Path(query).expanduser()
            if not rules.is_absolute() or not rules.is_file():
                raise ValueError("SARIF scan requires an existing absolute local Semgrep rules file; remote --config values are intentionally rejected")
            return [executable, "scan", "--config", str(rules.resolve()), "--sarif", "--output", str(_generated_artifact(project, adapter_id, "findings.sarif")), str(project)]
    raise ValueError(f"No command template exists for {adapter_id}:{operation_id}")


def run_native_operation(
    project_path: str | Path,
    adapter_id: str,
    operation_id: str,
    *,
    confirmed: bool = False,
    query: str = "",
    configured_executable: str | Path | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Run one documented local command after an explicit confirmation.

    This is intentionally not a generic shell endpoint.  It prevents an API
    caller or UI string from becoming a shell command, while leaving every
    upstream project free to provide its own advanced CLI/MCP surface.
    """
    project = Path(project_path).expanduser().resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"project path does not exist: {project}")
    operation = _operation(adapter_id, operation_id)
    generated = {
        ("openapi", "bundle"): project / ".codeslicer" / "generated" / "openapi" / "openapi.bundle.yaml",
        ("scip", "index"): project / ".codeslicer" / "generated" / "scip" / "index.scip",
        ("cyclonedx", "generate"): project / ".codeslicer" / "generated" / "cyclonedx" / "bom.json",
        ("spdx", "generate"): project / ".codeslicer" / "generated" / "spdx" / "sbom.spdx.json",
        ("sarif", "scan"): project / ".codeslicer" / "generated" / "sarif" / "findings.sarif",
    }.get((adapter_id, operation_id))
    if operation.requires_confirmation and not confirmed:
        return {
            "status": "confirmation_required", "adapter_id": adapter_id, "operation": operation_id,
            "message": "This local native operation can index files or create local tool state. Repeat with confirmed=true.",
            "privacy": {"mode": "explicit-local-process", "network_used_by_codeslicer": False, "external_process_network_behavior": "not guaranteed"},
        }
    query = str(query or "").strip()
    if operation.requires_query and not query:
        raise ValueError(f"{adapter_id}:{operation_id} requires a non-empty query")
    timeout = max(1, min(int(timeout_seconds), MAX_TIMEOUT_SECONDS))
    command = _command(adapter_id, operation_id, project, query, configured_executable)
    try:
        environment = None
        if adapter_id == "joern" and (java_home := _joern_java_home()):
            environment = {**os.environ, "JAVA_HOME": java_home, "PATH": str(Path(java_home) / "bin") + os.pathsep + os.environ.get("PATH", "")}
        completed = subprocess.run(command, cwd=str(project), text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, shell=False, check=False, env=environment)
        stdout, stderr = completed.stdout[-MAX_OUTPUT_CHARS:], completed.stderr[-MAX_OUTPUT_CHARS:]
        return {
            "status": "completed" if completed.returncode == 0 else "failed",
            "adapter_id": adapter_id, "operation": operation_id, "command": command,
            "returncode": completed.returncode, "stdout": stdout, "stderr": stderr,
            "truncated": len(completed.stdout) > MAX_OUTPUT_CHARS or len(completed.stderr) > MAX_OUTPUT_CHARS,
            "generated_artifact": str(generated) if generated and generated.is_file() else None,
            "privacy": {"mode": "explicit-local-process", "network_used_by_codeslicer": False, "external_process_network_behavior": "not guaranteed"},
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout", "adapter_id": adapter_id, "operation": operation_id, "command": command,
            "stdout": str(exc.stdout or "")[-MAX_OUTPUT_CHARS:], "stderr": str(exc.stderr or "")[-MAX_OUTPUT_CHARS:],
            "timeout_seconds": timeout,
            "privacy": {"mode": "explicit-local-process", "network_used_by_codeslicer": False, "external_process_network_behavior": "not guaranteed"},
        }
