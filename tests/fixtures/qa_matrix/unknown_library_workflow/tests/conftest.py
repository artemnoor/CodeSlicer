"""Pytest path setup.

The app imports `strangebus`, `magicqueue`, and `internal_utils_dev` as if they
were third-party packages. Tests prepend local stubs so no external API or real
package installation is required.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUBS = ROOT / "tests" / "stubs"

for path in (ROOT, STUBS):
    value = str(path)
    if value in sys.path:
        sys.path.remove(value)
    sys.path.insert(0, value)
