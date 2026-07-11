import json
import subprocess
import sys
from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument
from impact_engine.runtime_trace import runtime_trace_project_core


def _write_project(root: Path) -> None:
    (root / "tests").mkdir()
    (root / "repositories.py").write_text(
        """
class OrderRepository:
    def save(self, order):
        return {"saved": order}
""",
        encoding="utf-8",
    )
    (root / "services.py").write_text(
        """
from repositories import OrderRepository


class OrderService:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create_order(self, order):
        return self.repository.save(order)
""",
        encoding="utf-8",
    )
    (root / "tests" / "test_orders.py").write_text(
        """
from repositories import OrderRepository
from services import OrderService


def test_create_order_route_hits_service_chain():
    service = OrderService(repository=OrderRepository())
    assert service.create_order({"id": 1})["saved"] == {"id": 1}
""",
        encoding="utf-8",
    )


def test_runtime_trace_project_core_boosts_matched_edge(tmp_path: Path):
    _write_project(tmp_path)
    graph_path = tmp_path / "graph.json"
    analyze_project_core(str(tmp_path), out_path=str(graph_path))

    result = runtime_trace_project_core(
        str(tmp_path),
        graph_path=str(graph_path),
        test_command=[sys.executable, "-m", "pytest", "-q"],
        timeout_seconds=60,
    )

    assert result["status"] == "ok"
    assert result["summary"]["matched_edges"] >= 1
    graph = GraphDocument.from_dict(result["graph"])
    edge = next(
        item
        for item in graph.edges
        if item.from_node == "services.OrderService.create_order"
        and item.to_node == "repositories.OrderRepository.save"
    )
    assert edge.confidence >= 0.98
    assert edge.properties["runtime_confirmed"] is True
    assert edge.properties["confirmed_by_tests"]
    assert any(ev.source == "RUNTIME_CONFIRMED" for ev in edge.evidence)


def test_runtime_trace_cli_json_writes_patched_graph(tmp_path: Path):
    _write_project(tmp_path)
    graph_path = tmp_path / "graph.json"
    out_path = tmp_path / "graph.runtime.json"
    analyze_project_core(str(tmp_path), out_path=str(graph_path))

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "impact_engine.cli",
            "--json",
            "runtime-trace",
            str(tmp_path),
            "--graph",
            str(graph_path),
            "--out",
            str(out_path),
            "--",
            sys.executable,
            "-m",
            "pytest",
            "-q",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=80,
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"]["matched_edges"] >= 1
    assert out_path.exists()


def test_runtime_trace_mcp_wrapper(tmp_path: Path):
    _write_project(tmp_path)
    graph_path = tmp_path / "graph.json"
    analyze_project_core(str(tmp_path), out_path=str(graph_path))

    from impact_engine.mcp.server import TOOLS, runtime_trace

    assert any(tool["name"] == "runtime_trace" for tool in TOOLS)
    result = runtime_trace(
        str(tmp_path),
        graph_path=str(graph_path),
        test_command=[sys.executable, "-m", "pytest", "-q"],
    )

    assert result["status"] == "ok"
    assert result["result"]["summary"]["matched_edges"] >= 1
