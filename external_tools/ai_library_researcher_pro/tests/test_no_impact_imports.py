from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_impact_engine_imports_anywhere():
    forbidden = ["import impact_engine", "from impact_engine"]
    for path in (ROOT / "ai_library_researcher_pro").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert not any(term in lowered for term in forbidden), path
