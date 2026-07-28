"""Command dispatch for the public CLI."""
from impact_engine.cli_support import *


def dispatch_command(args: argparse.Namespace, parser: argparse.ArgumentParser, raw_argv: list[str]) -> None:
    if args.command == "daemon":
        from impact_engine.persistence import daemon_status, start_daemon, stop_daemon
        if args.daemon_command == "start":
            result = start_daemon(args.project)
        elif args.daemon_command == "status":
            result = daemon_status(args.project)
        elif args.daemon_command == "stop":
            result = stop_daemon(args.project)
        else:
            result = {"status": "error", "error": "daemon subcommand is required"}
        if args.json:
            _print_json(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("status") == "error":
            sys.exit(1)

    elif args.command == "agent":
        from impact_engine.agent_integration import client_catalog, detect_clients, doctor as agent_doctor_report, install, installation_status, repair, uninstall
        from impact_engine.terminal_ui import choose_agent_clients
        local_json = bool(getattr(args, "local_json", False) or getattr(args, "json", False))
        try:
            if args.agent_command == "detect":
                result = {"command": "agent.detect", "status": "ok", "changed": False, "result": {"clients": detect_clients(args.project)}, "warnings": [], "errors": []}
            elif args.agent_command == "list-clients":
                result = {"command": "agent.list-clients", "status": "ok", "changed": False, "result": {"clients": client_catalog()}, "warnings": [], "errors": []}
            elif args.agent_command == "status":
                result = installation_status(scope=args.scope, project_path=args.project)
            elif args.agent_command == "doctor":
                result = agent_doctor_report(timeout_seconds=args.timeout_seconds)
            elif args.agent_command == "install":
                requested = [value.strip() for value in args.client.split(",") if value.strip()]
                if requested == ["auto"]:
                    detected = [item for item in detect_clients(args.project) if item["detected"]]
                    found = [item["id"] for item in detected]
                    if not local_json and sys.stdin.isatty():
                        catalog = {item["id"]: item for item in client_catalog() if item["status"] != "unsupported"}
                        requested = choose_agent_clients(catalog, detected)
                        if "--scope" not in raw_argv:
                            # A one-command IDE setup should work in every
                            # project.  Scripts can still request project scope.
                            args.scope = "user"
                    else:
                        raise ValueError("interactive selection needs a terminal; pass --client <id> or --client all-detected --yes")
                elif requested == ["all-detected"]:
                    if not args.yes:
                        raise ValueError("--client all-detected requires --yes")
                    requested = [item["id"] for item in detect_clients(args.project) if item["detected"]]
                if not requested:
                    raise ValueError("no AI clients were selected or detected")
                result = install(requested, scope=args.scope, project_path=args.project, skills_only=args.skills_only, mcp_only=args.mcp_only, link=args.link, force=args.force, dry_run=args.dry_run, server_name=args.server_name, backup=not args.no_backup)
            elif args.agent_command == "repair":
                result = repair(scope=args.scope, project_path=args.project, force=args.force, dry_run=args.dry_run, backup=not args.no_backup)
            elif args.agent_command == "uninstall":
                result = uninstall(scope=args.scope, project_path=args.project, force=args.force, dry_run=args.dry_run)
            else:
                result = {"command": "agent", "status": "error", "changed": False, "result": {}, "warnings": [], "errors": ["agent subcommand is required"]}
        except (FileNotFoundError, OSError, ValueError) as exc:
            result = {"command": f"agent.{getattr(args, 'agent_command', 'unknown')}", "status": "error", "changed": False, "result": {}, "warnings": [], "errors": [str(exc)]}
        if local_json:
            _print_json(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("status") == "error":
            sys.exit(1)
        return

    elif args.command == "adapters":
        if args.adapter_command == "native":
            from impact_engine.adapters.native import native_profile, run_native_operation
            try:
                result = (
                    {"status": "ok", "adapter_id": args.adapter_id, "native": native_profile(args.adapter_id), "privacy": {"mode": "local-only", "network_used": False}}
                    if args.operation == "profile"
                    else run_native_operation(args.project, args.adapter_id, args.operation, confirmed=args.confirm, query=args.query, timeout_seconds=args.timeout_seconds)
                )
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") in {"error", "failed", "timeout"}:
                sys.exit(1)
            return
        if args.adapter_command in {"preflight", "status", "import"}:
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.adapter_command == "preflight":
                    result = registry.preflight(args.adapter_id)
                elif args.adapter_command == "status":
                    result = {"status": "ok", "adapter": registry.status(args.adapter_id), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.adapter_id == "lsp":
                    raise ValueError("LSP is a local process; configure it explicitly with `impact-engine adapters lsp configure`")
                else:
                    imported = registry.import_artifact(args.adapter_id, args.artifact)
                    adapter = registry.set_enabled(args.adapter_id, True) if args.enable else imported.get("adapter")
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": adapter, "privacy": {"mode": "local-only", "network_used": False}}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command == "verify-scip":
            from impact_engine.adapters.scip_interop import verify_golden_corpus
            result = verify_golden_corpus(args.corpus, run_lint=not args.no_lint)
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command == "lsp":
            from impact_engine.adapters.lsp import configure_lsp, disable_lsp, lsp_status, preflight_lsp, probe_lsp, query_lsp
            try:
                if args.lsp_command == "status":
                    result = {"status": "ok", "adapter": lsp_status(args.project), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "preflight":
                    result = {"status": "ok", "preflight": preflight_lsp(args.project, compile_commands=args.compile_commands), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "configure":
                    result = {"status": "ok", "adapter": configure_lsp(args.project, args.executable, args.workspace_roots, arguments=args.arguments, timeout_ms=args.timeout_ms, backend=args.backend, server_family=args.server_family, compile_commands=args.compile_commands), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "probe":
                    result = {"status": "ok", "adapter": probe_lsp(args.project), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "start":
                    from impact_engine.adapters.agent_lsp import start_agent_lsp_runtime
                    result = {"status": "ok", "adapter": start_agent_lsp_runtime(args.project), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "disable":
                    result = {"status": "ok", "adapter": disable_lsp(args.project), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "query":
                    result = query_lsp(args.project, method=args.method, file=args.file, line=args.line, character=args.character, query=args.query, entity_id=args.entity_id, timeout_ms=args.timeout_ms)
                    # `--graph` is meaningful only for an explicit LSP query:
                    # it lets the adapter expose exact/ambiguous mapping to
                    # the canonical graph without changing that graph.  The
                    # parser advertised the flag but previously ignored it.
                    if args.graph and result.get("status") == "ok":
                        from impact_engine.adapters.lsp import map_lsp_overlay
                        canonical = GraphDocument.from_json(Path(args.graph).read_text(encoding="utf-8"))
                        result = map_lsp_overlay(result, canonical)
                else:
                    result = {"status": "error", "error": "lsp subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command in {"openapi", "asyncapi"}:
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.boundary_command == "import":
                    imported = registry.import_artifact(args.adapter_command, args.spec)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.boundary_command == "enable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.boundary_command == "disable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.boundary_command == "status":
                    result = {"status": "ok", "adapter": registry.status(args.adapter_command), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": f"{args.adapter_command} subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command == "otel":
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.otel_command == "import":
                    imported = registry.import_artifact("otel", args.trace)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.otel_command == "enable":
                    result = {"status": "ok", "adapter": registry.set_enabled("otel", True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.otel_command == "disable":
                    result = {"status": "ok", "adapter": registry.set_enabled("otel", False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.otel_command == "status":
                    result = {"status": "ok", "adapter": registry.status("otel"), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": "otel subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command in {"cyclonedx", "spdx", "sarif"}:
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.security_command == "import":
                    imported = registry.import_artifact(args.adapter_command, args.report)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.security_command == "enable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.security_command == "disable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.security_command == "status":
                    result = {"status": "ok", "adapter": registry.status(args.adapter_command), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": f"{args.adapter_command} subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command in {"graphify", "codegraph"}:
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.external_graph_command == "import":
                    imported = registry.import_artifact(args.adapter_command, args.artifact)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.external_graph_command == "enable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.external_graph_command == "disable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.external_graph_command == "status":
                    result = {"status": "ok", "adapter": registry.status(args.adapter_command), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": f"{args.adapter_command} subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command == "joern":
            from impact_engine.adapters.registry import AdapterRegistry
            try:
                if args.joern_command == "import":
                    registry = AdapterRegistry(args.project)
                    imported = registry.import_artifact("joern", args.artifact)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.joern_command == "convert":
                    from impact_engine.adapters.joern_bridge import convert_graphson_file
                    result = convert_graphson_file(args.graphson, project_path=args.project, output_path=args.output)
                elif args.joern_command == "benchmark":
                    from impact_engine.adapters.joern_benchmark import run_joern_benchmark
                    case = None
                    if args.case_file:
                        case_path = Path(args.case_file).expanduser()
                        if not case_path.is_absolute():
                            raise ValueError("case_file must be an absolute local path")
                        case_data = json.loads(case_path.resolve().read_text(encoding="utf-8"))
                        cases = case_data.get("cases") if isinstance(case_data, dict) and isinstance(case_data.get("cases"), list) else [case_data]
                        if args.case_id:
                            case = next((item for item in cases if isinstance(item, dict) and item.get("case_id") == args.case_id), None)
                            if case is None:
                                raise ValueError(f"golden case not found: {args.case_id}")
                        elif len(cases) == 1:
                            case = cases[0]
                        else:
                            raise ValueError("case_id is required when case_file contains multiple cases")
                    result = run_joern_benchmark(args.project, args.artifact, case=case, output_path=args.output, entity=args.entity, max_nodes=args.max_nodes, max_edges=args.max_edges, max_paths=args.max_paths)
                elif args.joern_command == "discover":
                    from impact_engine.adapters.joern_benchmark import discover_local_joern_corpus
                    result = discover_local_joern_corpus(args.roots, max_files=args.max_files, timeout_seconds=args.timeout, include_synthetic=args.include_synthetic)
                elif args.joern_command == "enable":
                    registry = AdapterRegistry(args.project)
                    result = {"status": "ok", "adapter": registry.set_enabled("joern", True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.joern_command == "disable":
                    registry = AdapterRegistry(args.project)
                    result = {"status": "ok", "adapter": registry.set_enabled("joern", False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.joern_command == "status":
                    registry = AdapterRegistry(args.project)
                    result = {"status": "ok", "adapter": registry.status("joern"), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": "joern subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        from impact_engine.adapters.registry import AdapterRegistry
        registry = AdapterRegistry(args.project)
        try:
            if args.adapter_command == "list":
                result = {"status": "ok", "project_path": str(registry.project_path), "adapters": registry.list(), "privacy": {"mode": "local-only", "network_used": False}}
            elif args.adapter_command == "import-scip":
                imported = registry.import_artifact("scip", args.artifact)
                result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
            elif args.adapter_command in {"enable", "disable"}:
                result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_id, args.adapter_command == "enable"), "privacy": {"mode": "local-only", "network_used": False}}
            else:
                result = {"status": "error", "error": "adapter subcommand is required"}
        except (FileNotFoundError, ValueError, OSError) as exc:
            result = {"status": "error", "error": str(exc)}
        if args.json or getattr(args, "local_json", False):
            _print_json(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("status") == "error":
            sys.exit(1)

    elif args.command == "scan-plan":
        from impact_engine.scope import build_scan_plan, write_scan_plan
        plan = build_scan_plan(args.path)
        plan["plan_path"] = str(write_scan_plan(args.path, plan))
        if args.json or getattr(args, "local_json", False):
            _print_json(plan)
        else:
            print(f"Scan plan: {plan['plan_path']}")
            print(f"  Included files: {plan['included_files']}")
            print(f"  Excluded directories: {len(plan['excluded_directories'])}")

    elif args.command in {"visualize", "visualize-compare"}:
        from impact_engine.visualization import render_graph_comparison_html, render_graph_html

        try:
            if args.command == "visualize-compare":
                output = render_graph_comparison_html(args.impact_graph, args.graphify_graph, args.out)
                result = {"status": "ok", "impact_graph": args.impact_graph, "graphify_graph": args.graphify_graph, "html": str(output.as_posix())}
            else:
                output = render_graph_html(args.graph, args.out)
                result = {"status": "ok", "graph": args.graph, "html": str(output.as_posix())}
        except Exception as exc:
            result = {"status": "error", "graph": args.graph, "error": str(exc)}
        if args.json:
            _print_json(result)
        else:
            if result["status"] == "ok":
                print(f"Graph viewer created: {result['html']}")
            else:
                print(f"Graph viewer error: {result['error']}", file=sys.stderr)
        if result["status"] == "error":
            sys.exit(1)

    elif args.command == "analyze-incremental":
        from impact_engine.analysis.pipeline import analyze_project_core
        from impact_engine.incremental import incremental_update, load_snapshot, save_snapshot
        from contextlib import nullcontext
        from impact_engine.persistence import CacheLock, CancellationToken
        out_path = args.out or _project_graph_path(args.path)
        snapshot_path = args.snapshot or str(Path(args.path).resolve() / ".impact_engine" / "project.snapshot.json")
        previous = load_snapshot(snapshot_path) if Path(snapshot_path).exists() else None
        scope_key = __import__("hashlib").sha256((args.scope or ".").encode("utf-8")).hexdigest()[:12]
        raw_cache = str(Path(args.path).resolve() / ".impact_engine" / f"raw_graph.{scope_key}.json")
        cancellation = CancellationToken()
        from impact_engine.persistence import daemon_request, daemon_status
        daemon_running = not args.no_daemon and daemon_status(args.path).get("status") == "running"
        try:
            if daemon_running:
                result = daemon_request(args.path, "analyze-incremental", {
                    "out_path": out_path, "snapshot_path": snapshot_path,
                    "changed_files": args.changed, "scope": args.scope,
                })
            else:
                with CacheLock(args.path, owner="cli-incremental"):
                    result = incremental_update(
                    args.path,
                    lambda changed: analyze_project_core(
                        args.path,
                        out_path=None,
                        changed_files=changed,
                        raw_graph_cache_path=raw_cache,
                        scope=args.scope,
                        cancellation=cancellation,
                    ),
                    previous_snapshot=previous,
                    out_path=out_path,
                    previous_graph_path=out_path,
                    forced_changed=args.changed,
                    scope=args.scope,
                    cancellation=cancellation,
                    )
                    save_snapshot(result["incremental"]["snapshot"], snapshot_path)
        except KeyboardInterrupt:
            result = {"status": "cancelled", "incomplete": True, "diagnostics": ["analysis cancelled by user"]}
        _attach_runtime_contract(result, scope=args.scope)
        if args.json:
            _print_json(result)
        else:
            print(f"Incremental analysis: {result.get('status')}")
            print(f"  Changed files: {result.get('incremental', {}).get('changed_file_count', 0)}")
            print(f"  Graph: {result.get('graph_path') or out_path}")

    elif args.command == "watch":
        from impact_engine.analysis.pipeline import analyze_project_core
        from impact_engine.watch import watch_project
        from contextlib import nullcontext
        from impact_engine.persistence import CacheLock, CancellationToken
        out_path = args.out or _project_graph_path(args.path)
        cancellation = CancellationToken()
        from impact_engine.persistence import daemon_request, daemon_status
        if not args.no_daemon and daemon_status(args.path).get("status") == "running":
            daemon_result = daemon_request(args.path, "watch", {
                "out_path": out_path, "interval_seconds": args.interval,
                "iterations": args.iterations, "scope": args.scope,
            })
            results = daemon_result.get("iterations", [])
        else:
            with CacheLock(args.path, owner="cli-watch"):
                results = list(watch_project(
                args.path,
                lambda: analyze_project_core(args.path, out_path=None, scope=args.scope, cancellation=cancellation),
                interval_seconds=args.interval,
                iterations=args.iterations,
                out_path=out_path,
                scope=args.scope,
                cancellation=cancellation,
                ))
        result = results[-1] if results else {"incremental": {}}
        _attach_runtime_contract(result, scope=args.scope)
        if args.json:
            _print_json({"status": "ok", "iterations": results, **result})
        else:
            print(f"Watch completed: {len(results)} iteration(s)")
            print(f"  Last changed files: {result.get('incremental', {}).get('changed_file_count', 0)}")

    elif args.command == "graph-quality":
        from impact_engine.graph_quality import graph_quality_report
        graph = GraphDocument.from_json(Path(args.graph).read_text(encoding="utf-8"))
        result = graph_quality_report(graph)
        if args.json:
            _print_json(result)
        else:
            print(f"Graph quality: {result['status']}")
            print(f"  Nodes: {result['node_count']}; edges: {result['edge_count']}")
            print(f"  Orphans: {result['orphan_node_count']}; dangling edges: {result['dangling_edge_count']}")

    elif args.command == "unknown-regions":
        from impact_engine.unknown_regions import analyze_unknown_regions, build_research_requests, write_research_requests

        try:
            if args.graph:
                graph = GraphDocument.from_json(Path(args.graph).read_text(encoding="utf-8"))
                project_path = args.project_path or graph.metadata.get("project_path") or graph.metadata.get("path")
            elif args.project_path:
                from impact_engine.analysis.pipeline import analyze_project_core

                analysis = analyze_project_core(args.project_path)
                graph = GraphDocument.from_dict(analysis["graph"])
                project_path = args.project_path
            else:
                raise ValueError("Provide project_path or --graph")
            report = analyze_unknown_regions(graph)
            requests = build_research_requests(report, project_path=project_path)
            output_path = args.out
            if not output_path and project_path and Path(str(project_path)).is_dir():
                output_path = str(Path(str(project_path)) / ".impact_engine" / "unknown_region_tasks.json")
            if output_path:
                report["task_file"] = write_research_requests(requests, output_path)
            result = {"status": "ok", "report": report, "requests": requests}
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
        if args.json or args.local_json:
            _print_json(result)
        else:
            if result["status"] == "ok":
                report = result["report"]
                print(f"Unknown regions: {report['status']}")
                print(f"  Unresolved: {report['counts']['unresolved']}; suspicious: {report['counts']['suspicious']}")
                print(f"  AI tasks: {len(result['requests'])}")
                if report.get("task_file"):
                    print(f"  Task file: {report['task_file']}")
            else:
                print(f"Unknown-region error: {result['error']}", file=sys.stderr)
                sys.exit(1)

    elif args.command == "benchmark":
        from impact_engine.benchmarks import run_benchmark_suite, run_determinism_check, run_determinism_suite, run_mutation_suite, write_library_reports

        if args.benchmark_command == "run":
            result = run_benchmark_suite(args.root)
            determinism = run_determinism_suite(args.root, runs=3)
            Path(args.root).resolve().joinpath("determinism_report.json").write_text(json.dumps(determinism, indent=2, ensure_ascii=False), encoding="utf-8")
            result["determinism"] = determinism
            result["quality_gates"]["determinism_true"] = determinism["determinism"] is True
            if not result["quality_gates"]["determinism_true"]:
                result["status"] = "failed"
            Path(args.root).resolve().joinpath("benchmark_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        elif args.benchmark_command == "determinism":
            result = run_determinism_check(args.project_path, args.runs)
        elif args.benchmark_command == "mutate":
            result = run_mutation_suite(args.root)
            Path(args.root).resolve().joinpath("mutation_report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        elif args.benchmark_command == "libraries":
            result = write_library_reports(args.root)
        elif args.benchmark_command == "typescript":
            from impact_engine.benchmarks.typescript_support import run_typescript_support_benchmark
            result = run_typescript_support_benchmark(args.root)
        elif args.benchmark_command == "typescript-source":
            from impact_engine.benchmarks.source_typescript import run_source_typescript_benchmark
            result = run_source_typescript_benchmark(args.root)
        elif args.benchmark_command == "research-e2e":
            from impact_engine.research.real_e2e import run_real_research_e2e
            result = run_real_research_e2e(args.root)
        elif args.benchmark_command == "polyglot":
            from impact_engine.benchmarks.sprint5_polyglot import run_sprint5_benchmark
            result = run_sprint5_benchmark(args.root)
        else:
            result = {"status": "error", "error": "benchmark subcommand is required"}
        if args.json:
            _print_json(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("status") == "failed" or result.get("status") == "error":
            sys.exit(1)

    elif args.command == "onboard":
        from impact_engine.project_onboarding import onboard_project
        try:
            summary = onboard_project(
                args.source, allow_network=args.allow_network, workspace=args.workspace, branch=args.branch,
                graphify_mode=args.graphify, graphify_timeout_seconds=args.graphify_timeout,
            )
        except (FileNotFoundError, FileExistsError, PermissionError, RuntimeError, ValueError, OSError) as exc:
            summary = {"schema_version": "CodeSlicerProjectOnboarding/v1", "status": "error", "error": str(exc), "privacy": {"mode": "local-only", "network_used": False}}
        if args.out and summary.get("status") != "error":
            destination = Path(args.out).expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.json:
            _print_json(summary)
        else:
            print(f"Project onboarding: {summary.get('status')}")
            if summary.get("project"):
                print(f"  Project: {summary['project'].get('path')}")
            if summary.get("canonical_graph"):
                print(f"  CodeSlicer graph: {summary['canonical_graph'].get('nodes')} nodes, {summary['canonical_graph'].get('edges')} edges")
            if summary.get("architecture_graph"):
                print(f"  Graphify: {summary['architecture_graph'].get('status')}")
            for limitation in summary.get("limitations", []):
                print(f"  Limitation: {limitation}")
            if summary.get("error"):
                print(f"  Error: {summary['error']}", file=sys.stderr)
        if summary.get("status") == "error":
            sys.exit(1)

    elif args.command == "analyze":
        from impact_engine.analysis.pipeline import analyze_project_core
        from impact_engine.support_packs.detection import detect_unknown_libraries_core
        from contextlib import nullcontext
        from impact_engine.persistence import CacheLock, CancellationToken, daemon_request, daemon_status
        out_path = args.out or _project_graph_path(args.path)
        if args.use_scan_plan:
            from impact_engine.scope import build_scan_plan, write_scan_plan
            write_scan_plan(args.path, build_scan_plan(args.path))
        def report_progress(event):
            stream = sys.stderr if args.json else sys.stdout
            print(
                f"[{event['overall_percent']:>5.1f}%] {event['message']} "
                f"({event['processed']}/{event['total']})",
                file=stream,
                flush=True,
            )
        cancellation = CancellationToken()
        if not args.no_daemon and daemon_status(args.path).get("status") == "running":
            summary = daemon_request(args.path, "analyze", {
                "out_path": out_path, "scope": args.scope,
                "enable_remote_registry": args.remote_registry,
                "create_research_requests": not args.no_research_requests,
                "graphify_path": args.graphify,
            })
        else:
            with CacheLock(args.path, owner="cli-analyze"):
                summary = analyze_project_core(
                    args.path, out_path=out_path, enable_remote_registry=args.remote_registry,
                    create_research_requests=not args.no_research_requests, graphify_path=args.graphify,
                    progress_callback=report_progress, scope=args.scope, cancellation=cancellation,
                )

        try:
            unknown_libs = detect_unknown_libraries_core(args.path)
            summary["unknown_libraries_count"] = len(unknown_libs)
            summary["unknown libraries count"] = len(unknown_libs)
        except Exception:
            summary["unknown_libraries_count"] = 0
            summary["unknown libraries count"] = 0

        summary["extractors"] = summary["extractors_used"]
        summary["support pack errors"] = summary["support_pack_load_errors"]
        _attach_runtime_contract(summary, scope=args.scope)

        if args.json:
            _print_json(summary)
        else:
            print("Project analysis completed successfully.")
            print(f"  Path: {summary.get('path')}")
            print(f"  Status: {summary.get('status')}")
            print(f"  Nodes: {summary.get('nodes')}, Edges: {summary.get('edges')}")
            print(f"  Languages: {', '.join(summary.get('languages', []))}")
            print(f"  Extractors used: {', '.join(summary.get('extractors_used', []))}")
            print(f"  Graph saved to: {summary.get('graph_path')}")

    elif args.command == "impact":
        graph_path = args.graph_positional or args.graph
        if not graph_path:
            print("Error: Missing graph path", file=sys.stderr)
            sys.exit(1)
        graph_text = Path(graph_path).read_text(encoding="utf-8")
        graph = GraphDocument.from_json(graph_text)

        result = impact_query(
            graph,
            target=args.target or "",
            symbol=args.symbol,
            file_path=args.file_arg,
            direction=args.direction,
            max_depth=args.depth,
            min_confidence=args.min_confidence,
            full_context_tokens=args.full_context_tokens,
            selected_context_tokens=args.selected_context_tokens,
        )
        if args.json:
            _print_json(result)
        else:
            print("Impact Query Results:")
            print(f"  Target: {args.target or args.symbol or args.file_arg}")
            print(f"  Direction: {args.direction}")
            print(f"  Matched Nodes: {len(result.get('matched_nodes', []))}")
            print(f"  Affected Nodes: {len(result.get('affected_nodes', []))}")
            for n in result.get('affected_nodes', []):
                print(f"    - {n.get('id')} ({n.get('kind')})")
            ranking = result.get("impact_ranking", [])
            if ranking:
                print("  Impact Ranking:")
                for item in ranking[:10]:
                    print(
                        f"    - {item.get('node_id')}: score={item.get('impact_score', 0):.3f}, "
                        f"confidence={item.get('path_confidence', 0):.0%}, "
                        f"status={item.get('confidence_status')}"
                    )
            print(f"  {result.get('scoring', {}).get('compact')}")
            context = result.get("context_efficiency", {})
            if context.get("status") == "measured":
                print(
                    f"  Context: {context['full_context_tokens']:,} -> "
                    f"{context['selected_context_tokens']:,} tokens "
                    f"({context['saving_percent']:.1f}% saved)"
                )
            else:
                print(f"  Context: {context.get('label')}")

    elif args.command == "pr-review":
        from impact_engine.pr_review import pr_review_core

        diff_text = None
        if args.diff_file:
            diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        try:
            result = pr_review_core(
                args.project_path,
                graph_path=args.graph,
                diff_text=diff_text,
                max_depth=args.depth,
                min_confidence=args.min_confidence,
                max_results=args.max_results,
                include_full_evidence=args.full_evidence,
            )
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
        if args.json:
            _print_json(result)
        else:
            print("PR Impact Report:")
            print(f"  Status: {result.get('status')}")
            if result.get("status") == "ok":
                print(f"  Risk: {result.get('risk', {}).get('level')} ({result.get('risk', {}).get('score')})")
                print(f"  Changed files: {result.get('summary', {}).get('changed_files')}")
                print(f"  Changed symbols: {result.get('summary', {}).get('changed_symbols')}")
                print(f"  Top impacts: {result.get('summary', {}).get('top_impacts')}")
                print("  Risk reasons:")
                for reason in result.get("risk", {}).get("reasons", []):
                    print(f"    - {reason}")
                print("  Required tests:")
                for item in result.get("suggested_tests", {}).get("required", []):
                    print(f"    - {item.get('file') or item.get('node')} ({item.get('reason')})")
                print("  Recommended tests:")
                for item in result.get("suggested_tests", {}).get("recommended", []):
                    print(f"    - {item.get('file') or item.get('node')} ({item.get('reason')})")
            else:
                print(f"  Error: {result.get('error')}")
        if result.get("status") == "error":
            sys.exit(1)

    elif args.command == "review":
        from impact_engine.review import build_review_report
        from impact_engine.persistence import CacheLock, daemon_request, daemon_status
        from impact_engine.contracts import build_mode_response

        diff_text = Path(args.diff_file).read_text(encoding="utf-8") if args.diff_file else None
        try:
            if not args.no_daemon and daemon_status(args.project_path).get("status") == "running":
                result = daemon_request(args.project_path, "review", {
                    "diff_text": diff_text, "base": args.base, "graph_path": args.graph,
                    "refresh": args.refresh, "max_results": args.max_results,
                    "run_tests": args.run_tests, "deep": args.deep, "entity": args.entity,
                    "scope": args.scope,
                })
            else:
                graph = GraphDocument.from_json(Path(args.graph).read_text(encoding="utf-8")) if args.graph else None
                with CacheLock(args.project_path, owner="cli-review"):
                    result = build_review_report(
                        args.project_path, graph=graph, diff_text=diff_text, base=args.base,
                        graph_path=args.graph, refresh=args.refresh, max_results=args.max_results,
                        run_tests=args.run_tests, deep=args.deep, entity=args.entity, scope=args.scope,
                    )
            from impact_engine.review_history import record_review
            result["review_id"] = record_review(args.project_path, result)
            result["mode_response"] = build_mode_response(
                "review", project=args.project_path,
                freshness=result.get("graph_freshness"), coverage=result.get("coverage"),
                warnings=result.get("warnings", []), adapters=result.get("adapters", []), result=result,
            )
        except Exception as exc:
            result = {"status": "error", "error": str(exc), "schema_version": "ReviewReport/v1"}
        if args.json or getattr(args, "local_json", False):
            _print_json(result)
        else:
            print("Daily Review:")
            print(f"  Risk: {result.get('risk', {}).get('level')} (confidence: {result.get('risk', {}).get('confidence')})")
            print(f"  Graph: {result.get('graph_freshness', {}).get('refresh_mode')} / stale={result.get('graph_freshness', {}).get('stale')}")
            print("  Review now:")
            for item in result.get("top_impacts", []):
                print(f"    - {item.get('label')} [{item.get('kind')}] ({item.get('confidence')})")
            print("  Tests:")
            for item in result.get("test_recommendations", [])[:10]:
                print(f"    - {item.get('file')} ({item.get('priority')})")
            for warning in result.get("warnings", []):
                print(f"  Warning: {warning}")

    elif args.command in {"inspect", "investigate", "ci"}:
        from impact_engine.modes import build_ci_report, build_inspect_report, build_investigate_report, to_sarif
        from impact_engine.contracts import build_mode_response

        diff_text = Path(args.diff_file).read_text(encoding="utf-8") if getattr(args, "diff_file", None) else None
        exit_code = 0
        try:
            if args.command == "inspect":
                result = build_inspect_report(
                    args.project_path, entity=args.entity, graph_path=args.graph,
                    refresh=args.refresh, max_context=args.max_context,
                )
            elif args.command == "investigate":
                result = build_investigate_report(
                    args.project_path, entity=args.entity, graph_path=args.graph,
                    direction=args.direction, depth=args.depth, refresh=args.refresh,
                    runtime_validate=args.runtime_validate, max_nodes=args.max_nodes,
                    max_edges=args.max_edges,
                )
            else:
                result = build_ci_report(
                    args.project_path, base=args.base, policy_path=args.policy,
                    graph_path=args.graph, diff_text=diff_text, refresh=args.refresh,
                    run_tests=args.run_tests, test_command=args.test_command,
                )
                exit_code = int(result.get("exit_code", 0))
        except (FileNotFoundError, ValueError) as exc:
            exit_code = 2
            result = {
                "schema_version": "CodeSlicerModeReport/v1",
                "mode": args.command,
                "status": "invalid_input",
                "local_only": True,
                "error": str(exc),
                "warnings": [str(exc)],
                "coverage": [],
                "graph_freshness": {"status": "unavailable", "stale": True},
                "actions": {"items": []},
                "exit_code": exit_code,
            }
        except Exception as exc:
            exit_code = 3 if args.command == "ci" else 1
            result = {
                "schema_version": "CodeSlicerModeReport/v1",
                "mode": args.command,
                "status": "analysis_failed",
                "local_only": True,
                "error": str(exc),
                "warnings": [f"analysis could not complete: {exc}"],
                "coverage": [],
                "graph_freshness": {"status": "unavailable", "stale": True},
                "actions": {"items": []},
                "exit_code": exit_code,
            }
        result["mode_response"] = build_mode_response(
            args.command, project=args.project_path,
            freshness=result.get("graph_freshness"), coverage=result.get("coverage"),
            warnings=result.get("warnings", []), adapters=result.get("adapters", []), result=result,
        )
        output = to_sarif(result) if args.command == "ci" and args.format == "sarif" else result
        if getattr(args, "out", None):
            destination = Path(args.out).expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
            if not args.json and args.command == "ci":
                print(f"CodeSlicer CI report written: {destination}")
        elif args.json or getattr(args, "local_json", False) or args.command == "ci":
            _print_json(output)
        else:
            print(f"{args.command.capitalize()}: {result.get('status')}")
            if result.get("resolved_entity"):
                print(f"  Entity: {result['resolved_entity'].get('id')}")
            if result.get("risk"):
                print(f"  Risk: {result['risk'].get('level')}")
            for warning in result.get("warnings", []):
                print(f"  Warning: {warning}")
        if exit_code:
            sys.exit(exit_code)

    elif args.command == "runtime-trace":
        from impact_engine.runtime_trace import runtime_trace_project_core

        test_command = list(args.test_command or [])
        if test_command and test_command[0] == "--":
            test_command = test_command[1:]
        try:
            result = runtime_trace_project_core(
                args.project_path,
                graph_path=args.graph,
                out_path=args.out,
                test_command=test_command or None,
                timeout_seconds=args.timeout,
            )
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
        if args.json:
            _print_json(result)
        else:
            print("Runtime Trace Booster:")
            print(f"  Status: {result.get('status')}")
            print(f"  Runtime calls: {result.get('summary', {}).get('runtime_calls', 0)}")
            print(f"  Matched edges: {result.get('summary', {}).get('matched_edges', 0)}")
            print(f"  Unmatched calls: {result.get('summary', {}).get('unmatched_calls', 0)}")
            if result.get("out_path"):
                print(f"  Patched graph: {result.get('out_path')}")
            if result.get("error"):
                print(f"  Error: {result.get('error')}")
        if result.get("status") not in {"ok"}:
            sys.exit(1)

    elif args.command == "explain-edge":
        graph_path = args.graph_positional or args.graph
        if not graph_path:
            print("Error: Missing graph path", file=sys.stderr)
            sys.exit(1)
        graph_text = Path(graph_path).read_text(encoding="utf-8")
        graph = GraphDocument.from_json(graph_text)
        result = explain_edge(graph, args.from_node, args.to_node, args.kind)

        if args.json:
            _print_json(result)
        else:
            print("Edge Explanation:")
            print(f"  Found: {result.get('found')}")
            if result.get('found'):
                edge = result.get('edge', {})
                print(f"  From: {edge.get('from')}")
                print(f"  To: {edge.get('to')}")
                print(f"  Kind: {edge.get('kind')}")
                print(f"  Confidence: {result.get('confidence')}")
                print(f"  Source: {result.get('source')}")
                print("  Reasoning Steps:")
                for step in result.get('reasoning_steps', []):
                    print(f"    - {step}")
                print("  Evidence:")
                for ev in result.get('evidence_chain', []):
                    print(f"    - {ev.get('description')} ({ev.get('file')}:{ev.get('line')})")

    elif args.command == "detect-languages":
        from impact_engine.languages.registry import detect_languages
        langs = detect_languages(args.project_path)
        if args.json:
            _print_json(langs)
        else:
            print(f"Languages detected: {', '.join(langs)}")

    elif args.command == "inventory":
        from impact_engine.inventory.scanner import scan_project_inventory
        inv_res = scan_project_inventory(args.project_path)
        if args.json:
            _print_json(inv_res.to_dict())
        else:
            d = inv_res.to_dict()
            print("Project Inventory:")
            print(f"  Files: {d.get('files_count', 0)}")
            print(f"  Classes: {d.get('classes_count', 0)}")
            print(f"  Functions/Methods: {d.get('methods_count', 0)}")
            print(f"  LOC (Lines of Code): {d.get('loc', 0)}")

    elif args.command == "support-packs":
        from impact_engine.support_packs.store import SupportPackStore
        store = SupportPackStore()

        if args.sp_command == "list":
            packs = store.list_packs()
            from dataclasses import asdict
            if args.json:
                _print_json([asdict(p) for p in packs])
            else:
                print("Installed Support Packs:")
                for p in packs:
                    print(f"  - {p.library} ({p.language}, {p.version_range})")

        elif args.sp_command == "validate":
            from impact_engine.support_packs.registry import validate_support_pack_file
            res = validate_support_pack_file(args.path)
            if args.json:
                _print_json(res)
            else:
                if res["valid"]:
                    print(f"Support pack at '{args.path}' is VALID.")
                    print(f"  Library: {res.get('library')}")
                else:
                    print(f"Support pack at '{args.path}' is INVALID:")
                    for err in res.get("errors", []):
                        print(f"  - {err}")
            if not res["valid"]:
                sys.exit(1)

        elif args.sp_command == "install":
            try:
                from impact_engine.support_packs.schema import validate_support_pack_dict

                pack_dict = _load_support_pack_candidate(args.path)
                install_pack = pack_dict
                adapted_from = None
                validation_errors = validate_support_pack_dict(install_pack)
                if validation_errors:
                    try:
                        from impact_engine.research.pro_adapter import adapt_researcher_pro_draft
                        install_pack = adapt_researcher_pro_draft(pack_dict)
                        adapted_from = "ai_library_researcher_pro"
                        validation_errors = validate_support_pack_dict(install_pack)
                    except Exception as exc:
                        validation_errors = validation_errors + [f"researcher-pro adaptation failed: {exc}"]

                if validation_errors:
                    res = {"valid": False, "errors": validation_errors, "path": None}
                else:
                    target_path = _registry_pack_path(install_pack)
                    if target_path.exists() and not args.overwrite:
                        staged_path = _save_staged_support_pack(install_pack)
                        res = {
                            "valid": False,
                            "status": "blocked_existing_pack",
                            "errors": [f"Support pack already exists: {target_path.as_posix()}"],
                            "path": str(staged_path.as_posix()),
                            "target_path": str(target_path.as_posix()),
                            "message": "Existing pack was not overwritten. Use --overwrite if replacement is intentional.",
                        }
                    else:
                        res = store.validate_and_save_pack(install_pack)
                        res["status"] = "installed" if res.get("valid") else "error"
                        if adapted_from and res.get("valid", False):
                            res["adapted_from"] = adapted_from
                if args.json:
                    _print_json(res)
                else:
                    if res.get("valid", True):
                        print(f"Support pack for '{res.get('library')}' installed successfully at: {res.get('path')}")
                    else:
                        print("Support pack installation failed:")
                        for err in res.get("errors", []):
                            print(f"  - {err}")
                if not res.get("valid", True):
                    sys.exit(1)
            except Exception as e:
                err_dict = {"valid": False, "errors": [str(e)], "path": None}
                print(json.dumps(err_dict, indent=2, ensure_ascii=False) if args.json else f"Installation error: {str(e)}")
                sys.exit(1)

        elif args.sp_command == "adapt-pro-draft":
            try:
                from impact_engine.research.pro_adapter import adapt_researcher_pro_draft_file
                adapted = adapt_researcher_pro_draft_file(args.path)
                if args.out:
                    out_path = Path(args.out)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(json.dumps(adapted, indent=2, ensure_ascii=False), encoding="utf-8")
                    res = {"status": "ok", "path": str(out_path), "support_pack": adapted}
                else:
                    res = {"status": "ok", "support_pack": adapted}
                if args.json:
                    _print_json(res)
                else:
                    print("Researcher-pro draft adapted successfully.")
                    if args.out:
                        print(f"  Output: {args.out}")
            except Exception as e:
                res = {"status": "error", "errors": [str(e)]}
                if args.json:
                    _print_json(res)
                else:
                    print(f"Adaptation error: {e}")
                sys.exit(1)

    elif args.command == "project-packs":
        from impact_engine.project_packs import initialize_project_packs, install_project_pack, list_project_packs

        if args.project_packs_command == "init":
            res = initialize_project_packs(args.project_path)
        elif args.project_packs_command == "list":
            res = {"status": "ok", "scope": "project_local", "packs": list_project_packs(args.project_path)}
        elif args.project_packs_command == "install":
            res = install_project_pack(
                args.project_path,
                args.pack_path,
                trust_level=args.trust_level,
                overwrite=args.overwrite,
            )
        else:
            res = {"status": "error", "error": "project-packs subcommand is required"}
        if args.json:
            _print_json(res)
        else:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        if res.get("status") == "error":
            sys.exit(1)

    elif args.command == "libraries":
        if args.libraries_command == "detect":
            from impact_engine.support_packs.detection import detect_unknown_libraries_core
            unknown = detect_unknown_libraries_core(args.project_path)
            res = {"status": "ok", "project_path": args.project_path, "unknown_libraries": unknown, "count": len(unknown)}
            if args.json:
                _print_json(res)
            else:
                print("Unknown Libraries:")
                if not unknown:
                    print("  none")
                for library in unknown:
                    print(f"  - {library}")

        elif args.libraries_command == "research":
            if args.pro:
                try:
                    res = _run_researcher_pro(args)
                except Exception as exc:
                    res = {"status": "error", "error": str(exc)}
                if args.json:
                    _print_json(res)
                else:
                    print("Library research workflow completed with ai_library_researcher_pro.")
                    print(f"  Workflow ID: {res.get('workflow_id')}")
                    print(f"  Support pack draft: {res.get('support_pack_path')}")
                    if res.get("install_result"):
                        print(f"  Install: {res['install_result']}")
                install_result = res.get("install_result")
                if (
                    res.get("status") == "error"
                    or res.get("ok") is False
                    or (isinstance(install_result, dict) and install_result.get("valid") is False)
                ):
                    sys.exit(1)
                return

            from impact_engine.research.workflow import init_workflow, fetch_pages, build_input_pack
            workflow_id = init_workflow(args.project_path, args.library, args.ecosystem)
            fetched_count = 0
            input_pack = None
            if args.allow_network:
                fetched_count = len(fetch_pages(workflow_id))
            if args.build_input or args.allow_network:
                input_pack = build_input_pack(workflow_id)
            res = {
                "status": "initialized",
                "workflow_id": workflow_id,
                "project_path": args.project_path,
                "library": args.library,
                "ecosystem": args.ecosystem,
                "network_fetches": fetched_count,
                "input_pack_built": input_pack is not None,
            }
            if input_pack is not None:
                res["agent_task_path"] = str(
                    (Path(".impact_engine/research_workflows") / workflow_id / "agent_task.json").as_posix()
                )
            if args.json:
                _print_json(res)
            else:
                print("Library research workflow initialized.")
                print(f"  Workflow ID: {workflow_id}")
                print(f"  Library: {args.library} ({args.ecosystem})")
                if input_pack is not None:
                    print("  Research input pack built.")
                    print(f"  Agent task: {res['agent_task_path']}")
        else:
            print("Error: Missing libraries subcommand", file=sys.stderr)
            sys.exit(1)

    elif args.command == "db":
        from impact_engine.storage.db import init_db, list_analysis_runs, get_default_db_path
        db_p = args.path if args.path else None

        if args.db_command == "init":
            initialized_path = init_db(db_p)
            res = {"status": "ok", "db_path": str(initialized_path.as_posix())}
            if args.json:
                _print_json(res)
            else:
                print(f"Database initialized at: {initialized_path}")

        elif args.db_command == "runs":
            runs = list_analysis_runs(db_p or get_default_db_path())
            if args.json:
                _print_json(runs)
            else:
                print("Analysis Runs:")
                for r in runs:
                    print(f"  - Run ID: {r.get('run_id')} (Timestamp: {r.get('timestamp')}, Path: {r.get('project_path')})")

    elif args.command == "research":
        from impact_engine.research.workflow import (
            init_workflow, fetch_pages, build_input_pack, validate_candidate, install_candidate
        )

        if args.research_command == "start":
            wf_id = init_workflow(args.project_path, args.library, args.ecosystem)
            res = {"status": "initialized", "workflow_id": wf_id}
            if args.json:
                _print_json(res)
            else:
                print("Research workflow initialized.")
                print(f"  Workflow ID: {wf_id}")

        elif args.research_command == "fetch":
            res = fetch_pages(args.workflow_id)
            out = {"status": "fetched", "pages_count": len(res)}
            if args.json:
                _print_json(out)
            else:
                print(f"Fetched {len(res)} pages for workflow '{args.workflow_id}'.")

        elif args.research_command == "build-input":
            res = build_input_pack(args.workflow_id)
            out = {"status": "input_built", "excerpts_count": len(res.get("fetched_pages", []))}
            if args.json:
                _print_json(out)
            else:
                print(f"Research input built with {len(res.get('fetched_pages', []))} page excerpts.")

        elif args.research_command == "validate":
            candidate = _load_support_pack_candidate(args.support_pack)
            res = validate_candidate(args.workflow_id, candidate)
            if args.json:
                _print_json(res)
            else:
                if res.get("valid", True):
                    print("Candidate support pack is VALID.")
                else:
                    print("Candidate support pack is INVALID:")
                    for err in res.get("errors", []):
                        print(f"  - {err}")
            if not res.get("valid", True):
                sys.exit(1)

        elif args.research_command == "install":
            candidate = _load_support_pack_candidate(args.support_pack)
            res = install_candidate(args.workflow_id, candidate)
            if args.json:
                _print_json(res)
            else:
                if res.get("status") == "installed":
                    print(f"Candidate support pack installed at: {res.get('path')}")
                else:
                    print("Candidate installation failed:")
                    for err in res.get("errors", []):
                        print(f"  - {err}")
            if res.get("status") == "error":
                sys.exit(1)

    elif args.command == "doctor":
        res = _doctor_report(full=bool(getattr(args, "full", False)))
        if args.json:
            _print_json(res)
        else:
            print("Impact Engine Doctor:")
            print(f"  Status: {res['status']}")
            for check in res["checks"]:
                print(f"  - {check['name']}: {check['status']} - {check['message']}")
        if res["status"] == "error":
            sys.exit(1)

    elif args.command == "approvals":
        from impact_engine.approvals import ApprovalStore
        store = ApprovalStore(args.project_path)
        if args.approvals_command == "list":
            res = {"status": "ok", "project_path": str(Path(args.project_path).resolve()), "approvals": store.list()}
        elif args.approvals_command == "show":
            res = {"status": "ok", "approval": store.show(args.approval_id)}
        else:
            res = {"status": "approved", "approval": store.approve(args.approval_id)}
        if args.json:
            _print_json(res)
        else:
            print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "registry":
        from impact_engine.remote_registry import RegistryClient, ResearchRequestRecord

        client = RegistryClient()
        if args.registry_command == "status":
            res = client.connection_status()
        elif args.registry_command == "cache-pack":
            pack = _load_support_pack_candidate(args.path)
            res = client.cache_support_pack(pack)
        elif args.registry_command == "pull-pack":
            res = client.pull_support_pack(args.ecosystem, args.library)
        elif args.registry_command == "create-research-request":
            request = ResearchRequestRecord(
                ecosystem=args.ecosystem,
                library_name=args.library,
                package_name=args.package_name,
                project_fingerprint=args.project_fingerprint,
            )
            res = client.create_research_request(request)
        elif args.registry_command == "sync-project":
            from dataclasses import asdict
            from impact_engine.inventory.scanner import scan_project_inventory
            from impact_engine.remote_registry.sync import sync_registry_for_inventory

            inv = asdict(scan_project_inventory(args.project_path))
            res = sync_registry_for_inventory(inv, create_research_requests=not args.no_research_requests)
        elif args.registry_command == "process-queue":
            from impact_engine.remote_registry.worker import process_local_research_queue

            res = process_local_research_queue(
                project_path=args.project_path,
                limit=args.limit,
                allow_network=args.allow_network,
            )
        elif args.registry_command == "register-library":
            res = client.register_library(
                args.ecosystem, args.library, docs_url=args.docs_url,
                repository_url=args.repository_url, package_manager=args.package_manager,
            )
        elif args.registry_command == "library-status":
            res = client.library_status(args.ecosystem, args.library)
        elif args.registry_command == "approve-pack":
            res = client.approve_support_pack(args.pack_id, args.trust_level, args.reviewer, args.note)
        elif args.registry_command == "doc-check":
            res = client.record_documentation_check(
                args.ecosystem, args.library, args.url, args.content_hash, args.source_type
            )
        elif args.registry_command == "simulate-lifecycle":
            res = client.simulate_library_lifecycle(args.ecosystem, args.library, args.source_url)
        else:
            print("Error: Missing registry subcommand", file=sys.stderr)
            sys.exit(1)
        if args.json:
            _print_json(res)
        else:
            print(f"Registry: {res.get('status')}")
            if res.get("mode"):
                print(f"  Mode: {res.get('mode')}")
            if res.get("path"):
                print(f"  Path: {res.get('path')}")
        if res.get("status") == "error":
            sys.exit(1)

    elif args.command == "qa":
        if args.qa_command == "run":
            try:
                res = _qa_run(args.projects_root, args.out_dir)
            except Exception as exc:
                res = {"status": "error", "error": str(exc)}
            if args.json:
                _print_json(res)
            else:
                print("QA Run:")
                print(f"  Status: {res.get('status')}")
                if res.get("summary"):
                    print(f"  Summary: {res.get('summary')}")
                for run in res.get("runs", []):
                    print(f"  - {run.get('project')}: {run.get('status')} ({run.get('nodes', 0)} nodes, {run.get('edges', 0)} edges)")
                    failed = [c for c in run.get("checks", []) if c.get("status") in {"fail", "known_gap"}]
                    for check in failed[:8]:
                        print(f"      {check.get('status')}: {check.get('type')} {check.get('description') or check.get('contains') or check.get('to')}")
            if res.get("status") in {"error", "failed"}:
                sys.exit(1)
        else:
            print("Error: Missing qa subcommand", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()
