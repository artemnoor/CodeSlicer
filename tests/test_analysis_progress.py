from pathlib import Path

import pytest

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.persistence import AnalysisCancelled, CancellationToken


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


def test_full_analysis_reports_file_level_extraction_and_stops_at_next_file(tmp_path):
    for index in range(40):
        (tmp_path / f"module_{index}.py").write_text(
            f"def value_{index}():\n    return {index}\n",
            encoding="utf-8",
        )
    token = CancellationToken()
    events = []

    def record(event):
        events.append(event)
        if event.get("stage") == "extraction" and event.get("processed", 0) >= 2:
            token.cancel()

    with pytest.raises(AnalysisCancelled):
        analyze_project_core(
            str(tmp_path),
            out_path=str(tmp_path / "graph.json"),
            progress_callback=record,
            cancellation=token,
        )

    extraction = [event for event in events if event.get("stage") == "extraction"]
    assert any(event.get("processed") == 1 for event in extraction)
    assert any(event.get("processed") == 2 for event in extraction)
    assert not (tmp_path / "graph.json").exists()
