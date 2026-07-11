from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(slots=True)
class HygieneRulePack:
    """Data-driven extension points for hygiene classification.

    This intentionally stores plain strings/lists/dicts only, so packs can be
    serialized, diffed, generated, and reviewed without importing this package.
    """

    known_common_dependencies: dict[str, list[str]] = field(default_factory=dict)
    stdlib_overrides: dict[str, list[str]] = field(default_factory=dict)
    file_role_patterns: dict[str, list[str]] = field(default_factory=dict)
    ignore_patterns: list[str] = field(default_factory=list)
    generated_markers: list[str] = field(default_factory=list)
    route_param_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "known_common_dependencies": {k: list(v) for k, v in sorted(self.known_common_dependencies.items())},
            "stdlib_overrides": {k: list(v) for k, v in sorted(self.stdlib_overrides.items())},
            "file_role_patterns": {k: list(v) for k, v in sorted(self.file_role_patterns.items())},
            "ignore_patterns": list(self.ignore_patterns),
            "generated_markers": list(self.generated_markers),
            "route_param_patterns": list(self.route_param_patterns),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HygieneRulePack":
        def dict_list(name: str) -> dict[str, list[str]]:
            raw = data.get(name, {}) or {}
            return {str(k): [str(x) for x in list(v)] for k, v in dict(raw).items()}

        return cls(
            known_common_dependencies=dict_list("known_common_dependencies"),
            stdlib_overrides=dict_list("stdlib_overrides"),
            file_role_patterns=dict_list("file_role_patterns"),
            ignore_patterns=[str(x) for x in list(data.get("ignore_patterns", []) or [])],
            generated_markers=[str(x) for x in list(data.get("generated_markers", []) or [])],
            route_param_patterns=[str(x) for x in list(data.get("route_param_patterns", []) or [])],
        )


def default_rule_pack() -> HygieneRulePack:
    return HygieneRulePack(
        known_common_dependencies={
            "python": [
                "fastapi",
                "pydantic",
                "sqlalchemy",
                "pytest",
                "celery",
                "django",
                "flask",
                "requests",
                "httpx",
                "uvicorn",
                "dependency_injector",
            ],
            "javascript": [
                "react",
                "react-dom",
                "react-router-dom",
                "@vitejs/plugin-react",
                "vite",
                "vitest",
                "typescript",
                "axios",
                "next",
                "express",
                "zod",
                "lodash",
            ],
            "typescript": [
                "react",
                "react-dom",
                "react-router-dom",
                "@vitejs/plugin-react",
                "vite",
                "vitest",
                "typescript",
                "axios",
                "next",
                "express",
                "zod",
                "lodash",
            ],
            "go": ["github.com/gin-gonic/gin", "github.com/stretchr/testify"],
            "java": ["org.springframework", "junit", "org.junit", "org.mockito"],
        },
        stdlib_overrides={
            "python": [
                "os",
                "sys",
                "json",
                "pathlib",
                "typing",
                "dataclasses",
                "uuid",
                "datetime",
                "asyncio",
                "collections",
                "functools",
                "itertools",
                "re",
                "math",
                "sqlite3",
                "logging",
                "subprocess",
                "email",
                "http",
                "urllib",
                "unittest",
                "enum",
                "abc",
                "contextlib",
                "inspect",
                "importlib",
                "tomllib",
                "hashlib",
                "tempfile",
                "shutil",
            ],
            "javascript": ["fs", "path", "url", "crypto", "http", "https", "stream", "events", "child_process", "util", "os", "buffer"],
            "typescript": ["fs", "path", "url", "crypto", "http", "https", "stream", "events", "child_process", "util", "os", "buffer"],
            "go": ["fmt", "net/http", "context", "encoding/json", "strings", "errors", "time", "os", "log", "testing"],
            "java": ["java", "javax"],
        },
        file_role_patterns={},
        ignore_patterns=[],
        generated_markers=["Code generated", "AUTO-GENERATED", "This file was generated", "DO NOT EDIT", "@generated"],
        route_param_patterns=[r"\{([^}/]+)\}", r":([A-Za-z_][A-Za-z0-9_]*)", r"<([^>/]+)>", r"\$\{([^}]+)\}"],
    )


def load_rule_pack(path: str | Path) -> HygieneRulePack:
    text = Path(path).read_text(encoding="utf-8")
    return HygieneRulePack.from_dict(json.loads(text))


def save_rule_pack(pack: HygieneRulePack, path: str | Path) -> None:
    Path(path).write_text(json.dumps(pack.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
