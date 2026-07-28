from pathlib import Path

from impact_engine.local_api import _render_graphify_native_html


def test_graphify_viewer_does_not_substitute_canonical_graph(tmp_path: Path) -> None:
    """A Graphify tab must not present CodeSlicer's graph as Graphify output."""
    canonical = tmp_path / ".impact_engine"
    canonical.mkdir()
    (canonical / "graph.json").write_text('{"nodes": [], "edges": []}', encoding="utf-8")

    html = _render_graphify_native_html(tmp_path)

    assert "ещё не построен" in html
    assert "Канонический граф CodeSlicer здесь намеренно не показывается" in html


def test_packaged_agent_skills_are_available_from_source_tree() -> None:
    skills_root = Path(__file__).parents[1] / "src" / "impact_engine" / "agent_skills"
    assert (skills_root / "code-intelligence-orchestrator" / "SKILL.md").is_file()
    assert (skills_root / "codeslicer-impact-analysis" / "SKILL.md").is_file()
    assert (skills_root / "graphify-architecture-analysis" / "SKILL.md").is_file()
    assert (skills_root / "project-onboarding-workflow" / "SKILL.md").is_file()
