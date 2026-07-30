from pathlib import Path

from impact_engine.review_source import detect_base_refs, review_source


def _runner(values):
    def run(_root: Path, args: list[str]):
        return values.get(tuple(args))
    return run


def test_origin_default_is_the_only_automatic_preference(tmp_path):
    runner = _runner({
        ("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"): "refs/remotes/origin/main",
        ("rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"): "abc",
    })
    result = detect_base_refs(tmp_path, runner=runner)
    assert result == {
        "status": "automatic", "base_ref": "refs/remotes/origin/main",
        "candidates": ["refs/remotes/origin/main"], "reason": "origin default branch",
    }


def test_multiple_conventional_branches_need_selection(tmp_path):
    runner = _runner({
        ("rev-parse", "--verify", "--quiet", "main"): "abc",
        ("rev-parse", "--verify", "--quiet", "develop"): "def",
    })
    result = detect_base_refs(tmp_path, runner=runner)
    assert result["status"] == "selection_required"
    assert result["candidates"] == ["main", "develop"]


def test_diff_file_source_does_not_invent_a_base(tmp_path):
    source = review_source(tmp_path, diff_file="C:/review.patch")
    assert source["kind"] == "diff_file"
    assert source["base"]["status"] == "not_required"
