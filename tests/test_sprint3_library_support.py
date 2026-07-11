from pathlib import Path
import json

from impact_engine.analysis.pipeline import analyze_project_core


def _write_library_fixture(root: Path) -> None:
    (root / "api.py").write_text(
        """
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy.orm import Session
from celery import Celery, shared_task

router = APIRouter(prefix='/shop')
app = FastAPI()
celery_app = Celery('orders')

def get_db() -> Session:
    return Session()

@router.post('/orders')
def create_order(db: Session = Depends(get_db)):
    db.add('order')
    db.commit()
    notify.delay('order')

@celery_app.task
def notify(value):
    return value

@shared_task
def unrelated_task(value):
    return value

app.include_router(router, prefix='/api/v1')
""",
        encoding="utf-8",
    )


def test_library_support_packs_emit_provenance_and_cross_library_edges(tmp_path: Path):
    _write_library_fixture(tmp_path)
    result = analyze_project_core(str(tmp_path))
    graph = result["graph"]
    edges = graph["edges"]

    routes = [edge for edge in edges if edge.get("kind") == "ROUTE_HANDLES"]
    assert any(edge.get("from") == "HTTP POST /api/v1/shop/orders" for edge in routes)
    assert any(edge.get("to") == "api.create_order" for edge in routes)

    fastapi_edges = [edge for edge in edges if edge.get("properties", {}).get("support_pack_library") == "fastapi"]
    sqlalchemy_edges = [edge for edge in edges if edge.get("properties", {}).get("support_pack_library") == "sqlalchemy"]
    celery_edges = [edge for edge in edges if edge.get("properties", {}).get("support_pack_library") == "celery"]
    assert fastapi_edges
    assert sqlalchemy_edges
    assert celery_edges
    for edge in fastapi_edges + sqlalchemy_edges + celery_edges:
        provenance = edge["properties"].get("support_pack")
        assert provenance and provenance["support_pack"] in {"python/fastapi", "python/sqlalchemy", "python/celery"}
        assert provenance["rule_id"]
        assert provenance["trust_level"] == "verified_on_fixture"
        assert edge["evidence"]

    assert not any(edge.get("to") == "external:sqlalchemy.session.fake" for edge in edges)
    assert not any(edge.get("to") == "external:celery.task:api.missing" for edge in edges)


def test_draft_library_pack_does_not_participate_in_normal_analysis(tmp_path: Path):
    _write_library_fixture(tmp_path)
    draft = {
        "library": "sqlalchemy",
        "version_range": ">=2",
        "language": "python",
        "status": "draft",
        "trust_level": "draft",
        "sources": [{"type": "official_docs", "url": "https://docs.sqlalchemy.org/"}],
        "patterns": [],
        "edge_rules": [{"id": "draft", "type": "method_call_alias", "match": {"method": ["add"]}, "emit": {"kind": "DEPENDS_ON", "source": "SUPPORT_PACK", "confidence": 0.99, "description": "draft"}}],
        "confidence_rules": [],
        "playground_cases": [],
    }
    result = analyze_project_core(str(tmp_path), support_packs=[draft])
    assert result["graph"]["metadata"].get("support_pack_skipped")
    assert not any(edge.get("properties", {}).get("support_pack_library") == "sqlalchemy" for edge in result["graph"]["edges"])


def test_sprint3_pack_contracts_and_sqlalchemy_negative_receiver(tmp_path: Path):
    _write_library_fixture(tmp_path)
    (tmp_path / "negative.py").write_text(
        "from sqlalchemy.orm import Session\n\n"
        "def unrelated(other):\n    other.commit()\n",
        encoding="utf-8",
    )
    result = analyze_project_core(str(tmp_path))
    assert not any(
        edge.get("properties", {}).get("support_pack_library") == "sqlalchemy"
        and edge.get("from") == "negative.unrelated"
        for edge in result["graph"]["edges"]
    )

    for path in (
        Path("support_packs/python/fastapi/support_pack.json"),
        Path("support_packs/python/sqlalchemy/support_pack.json"),
        Path("support_packs/python/dependency_injector/support_pack.json"),
        Path("support_packs/python/celery/support_pack.json"),
    ):
        pack = json.loads(path.read_text(encoding="utf-8"))
        assert len(pack["fixtures"]) >= 4
        assert len(pack["negative_cases"]) >= 2
        assert len(pack["mutation_scenarios"]) >= 3
