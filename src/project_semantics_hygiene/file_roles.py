from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath

from .models import FileClassification, FileRole, ProjectFile
from .rule_pack import HygieneRulePack, default_rule_pack

_LANGUAGE_BY_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".kt": "kotlin",
    ".swift": "swift",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".rst": "rst",
}

_CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".cs",
    ".rb",
    ".php",
    ".rs",
    ".kt",
    ".swift",
}


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _segments(path: str) -> list[str]:
    return [s for s in _norm(path).split("/") if s]


def _filename(path: str) -> str:
    return PurePosixPath(_norm(path)).name


def _suffix(path: str) -> str:
    name = _filename(path)
    # Special-case .env.example before PurePath suffix handling.
    if name == ".env.example":
        return ".example"
    return PurePosixPath(name).suffix.lower()


def _has_segment(path: str, candidates: set[str]) -> bool:
    return any(s.lower() in candidates for s in _segments(path))


def _contains_segment_like(path: str, token: str) -> bool:
    return any(token in s.lower() for s in _segments(path))


def _match_any(path: str, patterns: list[str]) -> bool:
    normalized = _norm(path)
    return any(fnmatch.fnmatch(normalized, p) or fnmatch.fnmatch(_filename(normalized), p) for p in patterns)


class FileRoleClassifier:
    def __init__(self, rule_pack: HygieneRulePack | None = None):
        self.rule_pack = rule_pack or default_rule_pack()

    def classify_many(self, files: list[ProjectFile]) -> list[FileClassification]:
        return [self.classify_path(f.path, f.content) for f in files]

    def classify_path(self, path: str, content: str | None = None) -> FileClassification:
        p = _norm(path)
        low = p.lower()
        fname = _filename(p)
        fname_low = fname.lower()
        reasons: list[str] = []
        tags: list[str] = []
        language = self._language_for_path(p)

        for token, tag in [
            ("dead", "dead_candidate"),
            ("unused", "unused_candidate"),
            ("orphan", "unused_candidate"),
            ("legacy", "legacy_candidate"),
            ("deprecated", "legacy_candidate"),
        ]:
            if token in low:
                tags.append(tag)
                reasons.append(f"weak lifecycle keyword '{token}' adds tag only")

        if _match_any(p, self.rule_pack.ignore_patterns):
            tags.append("ignored_by_rule_pack")
            reasons.append("matched rule_pack ignore pattern")

        role, confidence, role_reasons = self._classify_role(p, content)
        reasons.extend(role_reasons)

        # Apply user/configurable additional role patterns after built-ins, but not
        # as an implicit replacement for higher-priority generated/vendor matches.
        custom_role, custom_confidence, custom_reasons = self._custom_role_match(p)
        if custom_role and self._priority(custom_role) < self._priority(role):
            role, confidence = custom_role, custom_confidence
            reasons.extend(custom_reasons)

        tags = sorted(set(tags))
        return FileClassification(
            path=path,
            role=role,
            confidence=confidence,
            reasons=reasons,
            tags=tags,
            language=language,
            is_generated=role == FileRole.GENERATED,
            is_test=role == FileRole.TEST,
            is_contract=role == FileRole.CONTRACT,
        )

    @staticmethod
    def _priority(role: FileRole) -> int:
        order = {
            FileRole.VENDOR: 0,
            FileRole.BUILD_ARTIFACT: 0,
            FileRole.GENERATED: 1,
            FileRole.TEST: 2,
            FileRole.CONTRACT: 3,
            FileRole.MIGRATION: 4,
            FileRole.FIXTURE: 5,
            FileRole.CONFIG: 6,
            FileRole.DOCS: 7,
            FileRole.SOURCE: 8,
            FileRole.UNKNOWN: 9,
        }
        return order[role]

    def _custom_role_match(self, path: str) -> tuple[FileRole | None, float, list[str]]:
        for raw_role, patterns in self.rule_pack.file_role_patterns.items():
            try:
                role = FileRole(raw_role)
            except ValueError:
                continue
            if _match_any(path, list(patterns)):
                return role, 0.88, [f"matched custom rule_pack pattern for {role.value}"]
        return None, 0.0, []

    def _classify_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]]:
        checks = [
            self._vendor_build_role,
            self._generated_role,
            self._test_role,
            self._contract_role,
            self._migration_role,
            self._fixture_role,
            self._config_role,
            self._docs_role,
        ]
        for check in checks:
            result = check(path, content)
            if result is not None:
                return result

        if _suffix(path) in _CODE_EXTENSIONS:
            return FileRole.SOURCE, 0.65, ["known source-code extension fallback"]
        return FileRole.UNKNOWN, 0.30, ["no strong semantic role match"]

    def _vendor_build_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]] | None:
        low_segments = [s.lower() for s in _segments(path)]
        vendor_segments = {"node_modules", ".venv", "venv", "site-packages"}
        build_segments = {"dist", "build", "target", ".next", "coverage"}
        if any(s in vendor_segments for s in low_segments):
            return FileRole.VENDOR, 0.98, ["path is inside vendor/runtime dependency directory"]
        if any(s in build_segments for s in low_segments):
            return FileRole.BUILD_ARTIFACT, 0.96, ["path is inside build artifact directory"]
        return None

    def _generated_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]] | None:
        low = path.lower()
        fname = _filename(path).lower()
        if any(seg in {"generated", "__generated__", "gen", "autogen", "proto"} for seg in [s.lower() for s in _segments(path)]):
            return FileRole.GENERATED, 0.95, ["path segment indicates generated code"]
        if any(token in low for token in ["/generated/", "/__generated__/", "/gen/", "/autogen/", "/proto/"]):
            return FileRole.GENERATED, 0.95, ["path contains generated-code directory token"]
        generated_names = [".generated.", "_generated.", ".gen.", "_pb2.py", "_pb2_grpc.py", ".g.dart", ".designer.cs", ".min.js", ".bundle.js"]
        if any(token in fname for token in generated_names):
            return FileRole.GENERATED, 0.96, ["filename indicates generated artifact"]
        if content:
            header = "\n".join(content.splitlines()[:20])
            for marker in self.rule_pack.generated_markers:
                if marker.lower() in header.lower():
                    return FileRole.GENERATED, 0.94, [f"content header contains generated marker '{marker}'"]
        return None

    def _test_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]] | None:
        fname = _filename(path)
        fname_low = fname.lower()
        if _has_segment(path, {"tests", "test", "__tests__", "spec"}):
            return FileRole.TEST, 0.94, ["path segment indicates tests"]
        patterns = [
            r"^test_.*\.py$",
            r"^.*_test\.py$",
            r"^.*\.test\.tsx?$",
            r"^.*\.spec\.tsx?$",
            r"^.*_test\.go$",
            r"^.*Test\.java$",
            r"^.*Tests\.cs$",
        ]
        for pat in patterns:
            if re.match(pat, fname) or re.match(pat, fname_low):
                return FileRole.TEST, 0.93, ["filename pattern indicates tests"]
        return None

    def _contract_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]] | None:
        fname = _filename(path).lower()
        if _has_segment(path, {"contracts", "schemas", "openapi", "proto"}):
            return FileRole.CONTRACT, 0.92, ["path segment indicates API/schema contract"]
        contract_names = {"openapi.json", "openapi.yaml", "openapi.yml", "swagger.json", "swagger.yaml", "swagger.yml", "graphql.schema"}
        if fname in contract_names:
            return FileRole.CONTRACT, 0.95, ["filename is a known contract/schema file"]
        if fname.endswith(".schema.json") or fname.endswith(".contract.json") or fname.endswith(".proto"):
            return FileRole.CONTRACT, 0.94, ["filename extension indicates contract/schema"]
        return None

    def _config_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]] | None:
        fname = _filename(path)
        fname_low = fname.lower()
        exact = {"pyproject.toml", "package.json", "tsconfig.json", "go.mod", "pom.xml", "build.gradle", "dockerfile", "docker-compose.yml", "docker-compose.yaml", ".env.example"}
        if fname_low in exact:
            return FileRole.CONFIG, 0.95, ["exact config/manifest filename"]
        config_tokens = ["eslint", "prettier", "vite", "webpack"]
        if any(tok in fname_low for tok in config_tokens) and ("config" in fname_low or fname_low.endswith(('.js', '.ts', '.cjs', '.mjs', '.json'))):
            return FileRole.CONFIG, 0.90, ["frontend/tooling config filename"]
        return None

    def _docs_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]] | None:
        fname_low = _filename(path).lower()
        if fname_low == "readme.md":
            return FileRole.DOCS, 0.95, ["README file"]
        if _has_segment(path, {"docs"}):
            return FileRole.DOCS, 0.91, ["path segment indicates documentation"]
        if _suffix(path) in {".md", ".rst"}:
            return FileRole.DOCS, 0.90, ["documentation extension"]
        return None

    def _migration_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]] | None:
        fname = _filename(path).lower()
        if _has_segment(path, {"migrations", "alembic"}) or "/db/migrate/" in f"/{path.lower()}/":
            return FileRole.MIGRATION, 0.92, ["path indicates migration directory"]
        if re.match(r"^\d{8,14}[_-].*\.(py|sql|js|ts)$", fname) or re.match(r"^\d{4}_\d{2}_\d{2}[_-].*\.(py|sql|js|ts)$", fname):
            return FileRole.MIGRATION, 0.88, ["filename resembles timestamped migration"]
        return None

    def _fixture_role(self, path: str, content: str | None) -> tuple[FileRole, float, list[str]] | None:
        if _has_segment(path, {"fixtures", "samples", "examples", "testdata"}):
            return FileRole.FIXTURE, 0.90, ["path segment indicates fixture/sample/example data"]
        return None

    def _language_for_path(self, path: str) -> str | None:
        fname = _filename(path).lower()
        if fname == "dockerfile":
            return "dockerfile"
        if fname in {"pom.xml"}:
            return "xml"
        if fname in {"go.mod"}:
            return "gomod"
        return _LANGUAGE_BY_EXT.get(_suffix(path))
