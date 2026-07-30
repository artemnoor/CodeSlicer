import pytest

from impact_engine.models import GraphDocument
from impact_engine.review import build_review_report


def test_diff_file_mode_requires_an_explicit_diff_file(tmp_path):
    with pytest.raises(ValueError, match="requires --diff-file"):
        build_review_report(str(tmp_path), graph=GraphDocument(), review_source_kind="diff-file", refresh="never")


def test_github_source_remains_a_no_network_contract(tmp_path):
    with pytest.raises(ValueError, match="no network request was made"):
        build_review_report(str(tmp_path), graph=GraphDocument(), review_source_kind="github-pr", refresh="never")
