import pytest

from impact_engine.models import GraphDocument
from impact_engine.review import build_review_report


def test_diff_file_mode_requires_an_explicit_diff_file(tmp_path):
    with pytest.raises(ValueError, match="requires --diff-file"):
        build_review_report(str(tmp_path), graph=GraphDocument(), review_source_kind="diff-file", refresh="never")


def test_github_source_remains_a_no_network_contract(tmp_path):
    with pytest.raises(ValueError, match="no network request was made"):
        build_review_report(str(tmp_path), graph=GraphDocument(), review_source_kind="github-pr", refresh="never")


def test_github_source_accepts_only_an_explicit_locally_prepared_diff(tmp_path):
    diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    report = build_review_report(str(tmp_path), graph=GraphDocument(), diff_text=diff, review_source_kind="github-pr", refresh="never")
    assert report["source"]["kind"] == "github_pull_request"
    assert report["source"]["label"] == "GitHub pull request (local diff)"
