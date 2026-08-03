from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_bundled_runtime.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("bundled_runtime_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_notices_use_the_checkout_version_for_impact_engine(monkeypatch):
    builder = _load_builder()

    class Distribution:
        metadata = {"Name": "impact_engine", "License": ""}
        version = "0.5.0"

    monkeypatch.setattr(builder.metadata, "distributions", lambda: [Distribution()])

    assert builder.third_party_notice_lines("0.5.3") == [
        "- impact_engine 0.5.3 — see installed distribution metadata"
    ]
