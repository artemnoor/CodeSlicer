import os
import shutil
import subprocess

import pytest


@pytest.mark.cli_installation
def test_installed_cli_bridge_help_in_clean_environment():
    """Prove the PATH executable works without source-tree import overrides."""
    if os.environ.get("CODESLICER_RUN_INSTALLED_CLI_TESTS") != "1":
        pytest.skip("opt-in: run this test in a clean installed environment")

    executable = shutil.which("impact-engine")
    assert executable, "impact-engine is not on PATH in the clean environment"
    environment = os.environ.copy()
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE"):
        environment.pop(variable, None)

    result = subprocess.run(
        [executable, "--json", "adapters", "joern", "convert", "--help"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    assert "joern" in output.lower()
    assert "graphson" in output.lower()
