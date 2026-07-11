from pathlib import Path

from impact_engine.analysis.pipeline import analyze_project_core


PROJECT = Path(__file__).parent / "fixtures" / "dependency_injector_project"


def test_analysis_reports_monotonic_stage_progress(tmp_path):
    events = []
    result = analyze_project_core(
        str(PROJECT),
        out_path=str(tmp_path / "graph.json"),
        progress_callback=events.append,
    )

    assert result["progress"]["status"] == "completed"
    assert events
    percentages = [event["overall_percent"] for event in events]
    assert percentages == sorted(percentages)
    assert percentages[-1] == 100.0
    assert all(event["processed"] <= event["total"] for event in events)
    assert result["graph"]["metadata"]["analysis_progress"]["current"]["overall_percent"] == 100.0
