from __future__ import annotations

import json
from pathlib import Path

from .models import HygieneReport


def to_json(report: HygieneReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def from_json_report(text: str) -> HygieneReport:
    return HygieneReport.from_dict(json.loads(text))


def dump_json(path: str | Path, report: HygieneReport) -> None:
    Path(path).write_text(to_json(report) + "\n", encoding="utf-8")


def load_json(path: str | Path) -> HygieneReport:
    return from_json_report(Path(path).read_text(encoding="utf-8"))
