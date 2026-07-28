from benchmarks.performance.runner import sanitize_performance_report


def test_performance_report_sanitizer_removes_urls_env_names_and_local_paths():
    report = sanitize_performance_report({
        "corpus": {"path": r"C:\private\JunMate"},
        "timings": {"warm": 0.47},
        "diagnostics": [{
            "message": "conflict at https://example.test/api using OPENROUTER_API_KEY",
            "details": "PROXYAPI_API_KEY",
        }],
    })
    rendered = str(report)
    assert report["corpus"]["path"] == "<local-corpus>"
    assert report["timings"]["warm"] == 0.47
    assert "https://example.test" not in rendered
    assert "OPENROUTER_API_KEY" not in rendered
    assert "PROXYAPI_API_KEY" not in rendered
    assert report["privacy"]["raw_source_diagnostics_stored"] is False
    assert report["privacy"]["redactions"]["urls"] == 1
    assert report["privacy"]["redactions"]["environment_names"] >= 2
