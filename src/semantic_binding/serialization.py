from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .facts import FactSet
from .models import ResolutionResult


def load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(data: Any, path: str | Path) -> None:
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_facts(path: str | Path) -> FactSet:
    return FactSet.from_dict(load_json(path))


def dump_result(result: ResolutionResult, path: str | Path) -> None:
    dump_json(result.to_dict(), path)
