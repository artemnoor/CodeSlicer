"""Path filtering helpers for runtime tracing."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

DEFAULT_EXCLUDE_PATTERNS = [
    ".venv",
    "venv",
    "site-packages",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
]


def normalize_patterns(patterns: list[str] | None) -> list[str]:
    return [str(pattern).replace("\\", "/") for pattern in (patterns or [])]


def is_path_included(
    filename: str,
    project_path: str | Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> bool:
    """Return whether *filename* should be traced.

    By default only files below *project_path* are included. Excludes match either
    path parts (for directory names such as ``.venv``) or fnmatch patterns against
    both the relative and absolute POSIX path.
    """

    if not filename or filename.startswith("<"):
        return False

    project = Path(project_path).resolve()
    try:
        path = Path(filename).resolve()
    except OSError:
        return False

    try:
        relative = path.relative_to(project)
    except ValueError:
        return False

    rel_posix = relative.as_posix()
    abs_posix = path.as_posix()
    excludes = normalize_patterns(DEFAULT_EXCLUDE_PATTERNS + (exclude_patterns or []))
    includes = normalize_patterns(include_patterns)

    for part in relative.parts:
        if part in excludes:
            return False

    for pattern in excludes:
        if fnmatch(rel_posix, pattern) or fnmatch(abs_posix, pattern):
            return False
        if "/" not in pattern and pattern in relative.parts:
            return False

    if includes:
        return any(fnmatch(rel_posix, pattern) or fnmatch(abs_posix, pattern) for pattern in includes)

    return True
