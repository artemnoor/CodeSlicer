"""Release gate: prove a built wheel works without the source checkout.

This intentionally covers the failure mode that unit tests cannot see: an
installed ``impact-engine-local-api`` must serve its bundled UI and discover
the manifest-backed language plugins from site-packages.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def _python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _command(venv: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return venv / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _get_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=2) as response:
        return json.loads(response.read())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="codeslicer-wheel-e2e-") as temporary:
        root = Path(temporary)
        wheel_dir = root / "wheel"
        venv = root / "venv"
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(wheel_dir)], cwd=ROOT, check=True)
        wheel = next(wheel_dir.glob("impact_engine-*.whl"))
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        python = _python(venv)
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], check=True)

        plugin_probe = subprocess.run(
            [
                str(python),
                "-c",
                "from impact_engine.plugin_architecture.registry import discover_plugin_registry; "
                "print(','.join(sorted(p.manifest.id for p in discover_plugin_registry().language_plugins())))",
            ],
            text=True,
            capture_output=True,
            check=True,
            cwd=root,
        )
        discovered_plugins = {item.strip() for item in plugin_probe.stdout.split(",") if item.strip()}
        assert {"language.python", "language.typescript", "language.csharp"} <= discovered_plugins

        # Framework support packs are runtime assets too: compat manifests
        # refer to them during a real installed analysis, not merely in a
        # source checkout.
        pack_probe = subprocess.run(
            [
                str(python),
                "-c",
                "from impact_engine.support_packs.paths import builtin_support_packs_root; "
                "root=builtin_support_packs_root(); "
                "assert (root/'python'/'fastapi'/'support_pack.json').is_file(); "
                "assert (root/'python'/'sqlalchemy'/'support_pack.json').is_file(); "
                "assert (root/'javascript'/'express'/'support_pack.json').is_file(); "
                "print(root)",
            ],
            text=True,
            capture_output=True,
            check=True,
            cwd=root,
        )
        assert pack_probe.stdout.strip()

        framework_analysis = """
from pathlib import Path
from tempfile import TemporaryDirectory
from impact_engine.analysis.pipeline import analyze_project_core
with TemporaryDirectory() as raw:
    project = Path(raw)
    (project / 'requirements.txt').write_text('fastapi\\nsqlalchemy\\n', encoding='utf-8')
    (project / 'app.py').write_text('from fastapi import FastAPI\\nfrom sqlalchemy import create_engine\\napp = FastAPI()\\n', encoding='utf-8')
    result = analyze_project_core(str(project), create_research_requests=False)
    libraries = {item['library'] for item in result['graph']['metadata'].get('support_pack_context', [])}
    assert {'fastapi', 'sqlalchemy'} <= libraries, libraries
"""
        subprocess.run([str(python), "-c", framework_analysis], cwd=root, check=True)

        port = _free_port()
        server = subprocess.Popen(
            [str(_command(venv, "impact-engine-local-api")), "--host", "127.0.0.1", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            cwd=root,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        page = response.read().decode("utf-8")
                    health = _get_json(f"http://127.0.0.1:{port}/api/health")
                    assert "CodeSlicer" in page
                    assert health["status"] == "ok"
                    print(f"wheel E2E OK: UI + API + plugins on port {port}")
                    return 0
                except OSError:
                    time.sleep(0.2)
            error = server.stderr.read() if server.stderr else ""
            raise RuntimeError(f"installed local API did not become ready: {error}")
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
