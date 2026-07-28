"""Locate built-in support packs in either a checkout or an installed wheel."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def builtin_support_packs_root() -> Path:
    """Return the immutable built-in pack directory shipped with CodeSlicer.

    A source checkout remains convenient for contributors.  A wheel instead
    stores exactly the same files under ``impact_engine.support_packs/builtin``.
    """
    checkout_root = Path(__file__).resolve().parents[3] / "support_packs"
    if checkout_root.is_dir():
        return checkout_root
    packaged = files("impact_engine.support_packs").joinpath("builtin")
    return Path(str(packaged))


def resolve_support_pack_root(root: str | Path | None = "support_packs") -> Path:
    """Resolve the default without hiding an explicitly supplied local root."""
    if root is None or str(root) in {"", "support_packs"}:
        candidate = Path("support_packs")
        return candidate.resolve() if candidate.is_dir() else builtin_support_packs_root()
    return Path(root).expanduser().resolve()
