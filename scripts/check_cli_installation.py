"""Verify that the installed ``impact-engine`` exposes this checkout."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from shutil import which


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (ROOT / "src").resolve()
PYTHON_OVERRIDE_VARIABLES = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE")


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent)
    except ValueError:
        return False
    return True


def _clean_subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in PYTHON_OVERRIDE_VARIABLES:
        environment.pop(variable, None)
    return environment


def check_installation() -> dict[str, object]:
    """Return a machine-readable installation check without installing anything."""
    spec = importlib.util.find_spec("impact_engine")
    module_path = Path(spec.origin).resolve() if spec and spec.origin else None
    executable = which("impact-engine")
    result: dict[str, object] = {
        "repository": str(ROOT),
        "source_root": str(SOURCE_ROOT),
        "module_path": str(module_path) if module_path else None,
        "module_matches_repository": bool(module_path and _within(module_path, SOURCE_ROOT)),
        "executable": executable,
        "executable_probe": "unavailable",
        "network_used": False,
    }

    if not executable:
        result.update(status="error", diagnostic="impact-engine executable is not on PATH")
    else:
        try:
            probe = subprocess.run(
                [executable, "--json", "adapters", "joern", "convert", "--help"],
                capture_output=True,
                env=_clean_subprocess_environment(),
                text=True,
                timeout=10,
                check=False,
            )
            help_text = f"{probe.stdout}\n{probe.stderr}".lower()
            supported = probe.returncode == 0 and "graphson" in help_text and "joern" in help_text
            result["executable_probe"] = "ok" if supported else "stale-or-incompatible"
            result["status"] = "ok" if supported else "error"
            if not supported:
                result["diagnostic"] = "impact-engine executable does not expose the current Joern bridge command in a clean environment"
        except (OSError, subprocess.TimeoutExpired) as exc:
            result.update(status="error", executable_probe="error", diagnostic=f"could not probe impact-engine executable: {type(exc).__name__}")

    if result.get("status") != "ok":
        result["recommendation"] = "install this checkout in editable mode before the demo, or make this check a CI gate"
    return result


def main() -> int:
    result = check_installation()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
