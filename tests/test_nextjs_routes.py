from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument


def test_nextjs_app_router_routes_are_evidence_backed(tmp_path: Path):
    route = tmp_path / "app" / "api" / "orders" / "route.ts"
    page = tmp_path / "app" / "dashboard" / "page.tsx"
    route.parent.mkdir(parents=True)
    page.parent.mkdir(parents=True)
    route.write_text(
        """export async function GET() { return Response.json({ ok: true }); }
export async function POST() { return Response.json({ created: true }); }
""",
        encoding="utf-8",
    )
    page.write_text("export default function Dashboard() { return <main />; }\n", encoding="utf-8")

    result = analyze_project_core(str(tmp_path))
    graph = GraphDocument.from_dict(result["graph"])
    routes = {node.id for node in graph.nodes if node.kind == "ROUTE"}

    assert {"HTTP GET /api/orders", "HTTP POST /api/orders", "HTTP GET /dashboard"} <= routes
    assert any(edge.kind == "ROUTE_HANDLES" and edge.from_node == "HTTP GET /api/orders" for edge in graph.edges)
    assert graph.metadata["nextjs_routes"]["status"] == "applied"
