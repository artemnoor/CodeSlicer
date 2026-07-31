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


def test_staged_source_does_not_read_unstaged_changes(tmp_path, monkeypatch):
    import impact_engine.review as review_module

    monkeypatch.setattr(review_module, "_git", lambda _root, args: "diff --git a/staged.py b/staged.py\n--- a/staged.py\n+++ b/staged.py\n@@ -1 +1 @@\n-old\n+new\n" if args[:2] == ["diff", "--cached"] else None)
    report = build_review_report(str(tmp_path), graph=GraphDocument(), review_source_kind="staged", refresh="never")
    assert report["source"]["kind"] == "staged"
    assert report["diff_source"] == "staged"
