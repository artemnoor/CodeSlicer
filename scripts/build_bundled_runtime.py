#!/usr/bin/env python3
"""Build one native, self-contained CodeSlicer runtime for a VS Code target.

The script deliberately refuses cross-target builds.  A platform VSIX must contain
native code produced on the corresponding OS/architecture runner, never a renamed
binary from another platform.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path


TARGETS = {"win32-x64", "win32-arm64", "darwin-x64", "darwin-arm64", "linux-x64", "linux-arm64"}


def host_target() -> str:
    system = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"x86_64", "amd64"} else machine
    if not system or f"{system}-{arch}" not in TARGETS:
        raise SystemExit(f"Unsupported native build host: {platform.system()}-{platform.machine()}")
    return f"{system}-{arch}"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=sorted(TARGETS))
    parser.add_argument("--extension-version", required=True)
    args = parser.parse_args()
    if args.target != host_target():
        raise SystemExit(f"Refusing to build {args.target} on {host_target()}. Use a native CI runner.")

    root = Path(__file__).resolve().parents[1]
    extension = root / "extensions" / "vscode"
    runtime = extension / "runtime" / args.target
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="codeslicer-runtime-") as temp:
        temp_path = Path(temp)
        hooks = temp_path / "hooks"
        hooks.mkdir()
        # Dynamic language plugins and packaged support packs are intentional runtime inputs.
        (hooks / "hook-impact_engine.py").write_text(
            "from PyInstaller.utils.hooks import collect_data_files, collect_submodules\n"
            "hiddenimports = collect_submodules('impact_engine') + collect_submodules('plugins')\n"
            "datas = collect_data_files('impact_engine')\n", encoding="utf-8"
        )
        launcher = temp_path / "codeslicer_launcher.py"
        launcher.write_text(
            "from multiprocessing import freeze_support\n"
            "import sys\n"
            # Framework hooks may run in a sandbox child process. PyInstaller
            # passes internal `parent_pid` arguments to that child; without
            # freeze_support it re-enters the CLI and waits forever.
            "freeze_support()\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'local-api':\n"
            "    del sys.argv[1]\n"
            "    from impact_engine.local_api import main\n"
            "    main()\n"
            "else:\n"
            "    from impact_engine.cli import main\n"
            "    raise SystemExit(main())\n",
            encoding="utf-8",
        )
        common = [
            # A one-file PyInstaller executable extracts a complete Python
            # environment into a temporary directory on every invocation.
            # On Windows that can be delayed indefinitely by endpoint
            # scanners and leaves an analysis lock behind when the editor
            # cancels it. A self-contained one-directory runtime is still
            # bundled in the VSIX, but starts deterministically in place.
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--additional-hooks-dir", str(hooks), "--paths", str(root / "src"),
            "--add-data", f"{root / 'support_packs'}{';' if sys.platform == 'win32' else ':'}support_packs",
            "--add-data", f"{root / 'plugins'}{';' if sys.platform == 'win32' else ':'}plugins",
            "--add-data", f"{root / 'frontend'}{';' if sys.platform == 'win32' else ':'}impact_engine/frontend",
            "--distpath", str(temp_path / "dist"), "--workpath", str(temp_path / "work"), "--specpath", str(temp_path),
        ]
        subprocess.run([*common, "--name", "codeslicer", str(launcher)], check=True, cwd=root)
        built = temp_path / "dist" / "codeslicer" / ("codeslicer.exe" if sys.platform == "win32" else "codeslicer")
        destination = runtime / "bin"
        shutil.copytree(built.parent, destination)
        executable = destination / built.name
        if sys.platform != "win32":
            executable.chmod(executable.stat().st_mode | 0o111)

    notices = runtime / "THIRD_PARTY_NOTICES_RUNTIME.md"
    distributions = []
    for item in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower() if d.metadata["Name"] else ""):
        name = item.metadata["Name"]
        if name:
            license_value = item.metadata.get("License") or ""
            license_summary = " ".join(license_value.strip().splitlines()[0].split()) if license_value.strip() else "see installed distribution metadata"
            distributions.append(f"- {name} {item.version} — {license_summary}")
    notices.write_text("# CodeSlicer bundled runtime notices\n\nEmbedded Python and dependency notices:\n\n" + "\n".join(distributions) + "\n", encoding="utf-8")
    shutil.copy2(root / "LICENSE", runtime / "LICENSE")
    files = {str(path.relative_to(runtime)).replace("\\", "/"): sha256(path) for path in runtime.rglob("*") if path.is_file()}
    manifest = {
        "runtimeVersion": metadata.version("impact-engine"),
        "extensionCompatibility": args.extension_version,
        "platform": args.target.rsplit("-", 1)[0],
        "arch": args.target.rsplit("-", 1)[1],
        "files": files,
    }
    (runtime / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
