"""Build hooks for distributable local UI assets.

The browser UI deliberately stays at repository root for easy development, but
the installed ``impact-engine-local-api`` must work without a checkout next to
it.  Copy the static assets into the ``impact_engine`` package during build so
the wheel is self-contained.
"""
from __future__ import annotations

from pathlib import Path
from shutil import copytree

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    def run(self) -> None:
        super().run()
        source = Path(__file__).parent / "frontend"
        destination = Path(self.build_lib) / "impact_engine" / "frontend"
        copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=lambda _directory, names: {name for name in names if name in {".cache", "node_modules"}},
        )


setup(cmdclass={"build_py": build_py})
