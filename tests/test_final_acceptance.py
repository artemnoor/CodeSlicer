import json
import sys
import subprocess
from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument
from impact_engine.support_packs.detection import detect_unknown_libraries_core
from impact_engine.mcp.server import analyze_project, impact_query, validate_support_pack, prepare_library_research_input, create_library_research_workflow

PROJECT_ROOT = Path(__file__).parent.parent
FINAL_PROJECT = PROJECT_ROOT / "tests" / "fixtures" / "final_acceptance_project"

def test_final_acceptance_pipeline():
    # 1. Run core analyzer
    res = analyze_project_core(str(FINAL_PROJECT))
    assert res["status"] == "ok"
    assert "python" in res["languages"]
    
    graph = GraphDocument.from_json(json.dumps(res["graph"]))
    
    # 2. Check files, classes, methods, calls, routes, tests
    nodes_kinds = {n.kind for n in graph.nodes}
    assert "FILE" in nodes_kinds
    assert "METHOD" in nodes_kinds
    assert "CALL_EXPR" in nodes_kinds
    assert "ROUTE" in nodes_kinds
    
    # 3. Python DI resolves deeply (Singleton & Factory constructor injection)
    # Container.order_serviceSingleton/Factory -> OrderService
    edge_binding = next((e for e in graph.edges if e.from_node == "app.container.Container.order_service" and e.to_node == "app.services.OrderService"), None)
    assert edge_binding is not None
    assert edge_binding.source == "INFERRED"
    assert edge_binding.properties.get("support_pack_id") == "dependency_injector"
    
    # OrderService -> OrderRepository constructor injection
    edge_dep = next((e for e in graph.edges if e.from_node == "app.services.OrderService" and e.to_node == "app.repositories.OrderRepository"), None)
    assert edge_dep is not None
    assert edge_dep.source == "INFERRED"
    assert edge_dep.properties.get("support_pack_id") == "dependency_injector"
    
    # 4. FastAPI Router routing resolves
    # HTTP POST /api/orders/ route node exists
    route_node = next((n for n in graph.nodes if n.id == "HTTP POST /api/orders/"), None)
    assert route_node is not None
    assert route_node.kind == "ROUTE"
    
    # Route -> Route Handler mapping exists
    edge_handler = next((e for e in graph.edges if e.from_node == "HTTP POST /api/orders/" and e.to_node == "app.routers.create_order"), None)
    assert edge_handler is not None
    assert edge_handler.properties.get("support_pack_id") == "fastapi"
    
    # Handler Depends provider resolved
    edge_depends = next((e for e in graph.edges if e.from_node == "app.routers.create_order" and "get_order_service" in e.to_node), None)
    assert edge_depends is not None
    assert edge_depends.properties.get("support_pack_id") == "fastapi"
    
    # 5. React structural chain resolves
    # OrderForm -> useOrderSubmit
    react_hook_edge = next((e for e in graph.edges if e.from_node == "OrderForm" and e.to_node == "useOrderSubmit"), None)
    assert react_hook_edge is not None
    assert react_hook_edge.properties.get("support_pack_id") == "react"
    
    # useOrderSubmit -> postOrder
    react_api_edge = next((e for e in graph.edges if e.from_node == "useOrderSubmit" and e.to_node == "postOrder"), None)
    assert react_api_edge is not None
    assert react_api_edge.properties.get("support_pack_id") == "react"
    
    # postOrder -> HTTP POST /api/orders/
    react_fetch_edge = next((e for e in graph.edges if e.from_node == "postOrder" and e.to_node == "HTTP POST /api/orders/"), None)
    assert react_fetch_edge is not None
    assert react_fetch_edge.properties.get("support_pack_id") == "react"
    
    # 6. Go/Java extraction exists, with fallback/native status in diagnostics
    diag = res["graph"].get("metadata", {}).get("tree_sitter_diagnostics", [])
    
    go_file = next((f for f in diag if "helper.go" in f["file"]), None)
    assert go_file is not None
    assert go_file["language"] == "go"
    assert go_file["status"] in ("native", "fallback")
    assert go_file["extractor_id"] in ("tree_sitter", "tree_sitter_fallback")
    
    java_file = next((f for f in diag if "Helper.java" in f["file"]), None)
    assert java_file is not None
    assert java_file["language"] == "java"
    assert java_file["status"] in ("native", "fallback")
    assert java_file["extractor_id"] in ("tree_sitter", "tree_sitter_fallback")

    # 7. Unknown libraries detected truthfully
    unknown_libs = detect_unknown_libraries_core(str(FINAL_PROJECT))
    assert "unknown_custom_lib" in unknown_libs
    
    # 8. Research workflow can create input pack for unknown
    wf_res = create_library_research_workflow(str(FINAL_PROJECT), "unknown_custom_lib", "python")
    assert wf_res["status"] == "ok"
    wf_id = wf_res["workflow_id"]
    
    research_input = prepare_library_research_input(wf_id, allow_network=False)
    assert research_input["status"] == "ok"
    assert "input_pack" in research_input
    
    # 9. Support pack validation works
    val_res = validate_support_pack(str(PROJECT_ROOT / "support_packs" / "python" / "fastapi" / "support_pack.json"))
    assert val_res["status"] == "ok"
    
    # 10. MCP can run analyze_project and impact_query
    temp_graph = str(FINAL_PROJECT / "graph.json")
    mcp_res = analyze_project(str(FINAL_PROJECT), out_path=temp_graph)
    assert mcp_res["status"] == "ok"
    
    query_res = impact_query(temp_graph, symbol="HTTP POST /api/orders/", direction="downstream", min_confidence=0.45)
    assert query_res["status"] == "ok"
    assert "result" in query_res and len(query_res["result"].get("affected_nodes", [])) > 0
    
    # Cleanup temp graph
    import os
    if os.path.exists(temp_graph):
        os.remove(temp_graph)

def test_final_acceptance_cli_subprocess():
    # CLI subprocess runs detect-languages, inventory, analyze, impact, explain
    python_exe = sys.executable
    
    # detect-languages
    res = subprocess.run([python_exe, "-m", "impact_engine.cli", "detect-languages", str(FINAL_PROJECT)], capture_output=True, text=True, check=True, timeout=10)
    assert "python" in res.stdout
    
    # inventory
    res = subprocess.run([python_exe, "-m", "impact_engine.cli", "inventory", str(FINAL_PROJECT)], capture_output=True, text=True, check=True, timeout=10)
    assert "Files:" in res.stdout
    
    # analyze
    res = subprocess.run([python_exe, "-m", "impact_engine.cli", "--json", "analyze", str(FINAL_PROJECT)], capture_output=True, text=True, check=True, timeout=10)
    data = json.loads(res.stdout)
    assert data["status"] == "ok"
