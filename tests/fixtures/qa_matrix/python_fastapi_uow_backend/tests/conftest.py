"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from app.dependencies import reset_dependencies


@pytest.fixture(autouse=True)
def _reset_dependencies():
    """Reset all module-level singletons before and after every test.

    Without this, the in-memory repositories would leak state between
    tests because FastAPI's dependency providers cache the UoW, the
    services and the repositories.
    """
    reset_dependencies()
    yield
    reset_dependencies()
