"""Pytest safety rails for the stabilization suite."""
from __future__ import annotations

import os
import signal

import pytest


@pytest.fixture(autouse=True)
def per_test_watchdog():
    """Fail a single test instead of letting the full suite hang forever.

    This is intentionally lightweight and Unix-only. On platforms without
    SIGALRM it becomes a no-op, so the test suite remains portable.
    """
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    timeout = int(os.environ.get("IMPACT_ENGINE_TEST_TIMEOUT", "60"))
    if timeout <= 0:
        yield
        return

    old_handler = signal.getsignal(signal.SIGALRM)

    def _on_timeout(signum, frame):  # pragma: no cover - only runs on hangs
        raise TimeoutError(f"pytest-level watchdog exceeded {timeout}s")

    signal.signal(signal.SIGALRM, _on_timeout)
    signal.alarm(timeout)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
