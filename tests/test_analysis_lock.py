import json
import os
import time
from pathlib import Path

import pytest

from impact_engine.analysis_lock import (
    AnalysisLockedError,
    acquire_analysis_lock,
    analysis_lock_path,
    release_analysis_lock,
)


def test_lock_excludes_live_owner_and_releases_cleanly(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    lock = acquire_analysis_lock(project, owner="test")
    assert analysis_lock_path(project).exists()
    with pytest.raises(AnalysisLockedError):
        acquire_analysis_lock(project, owner="second")

    release_analysis_lock(lock)
    assert not analysis_lock_path(project).exists()


def test_lock_reclaims_dead_owner_without_waiting_for_ttl(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    path = analysis_lock_path(project)
    path.parent.mkdir()
    path.write_text(
        json.dumps({"owner": "interrupted", "pid": 999_999_999, "hostname": os.uname().nodename if hasattr(os, "uname") else ""}),
        encoding="utf-8",
    )

    lock = acquire_analysis_lock(project, owner="recovered")
    assert lock.owner["owner"] == "recovered"
    release_analysis_lock(lock)


def test_live_local_owner_is_never_reclaimed_only_because_analysis_is_slow(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    lock = acquire_analysis_lock(project, owner="slow-analysis")
    old = time.time() - 24 * 60 * 60
    os.utime(lock.path, (old, old))

    with pytest.raises(AnalysisLockedError):
        acquire_analysis_lock(project, owner="second", stale_after_seconds=0.01)
    release_analysis_lock(lock)


def test_release_never_deletes_a_replacement_lock(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    lock = acquire_analysis_lock(project, owner="first")
    path = lock.path
    path.write_text(json.dumps({"owner": "replacement", "pid": os.getpid(), "created_at": "new"}), encoding="utf-8")

    release_analysis_lock(lock)
    assert json.loads(path.read_text(encoding="utf-8"))["owner"] == "replacement"
