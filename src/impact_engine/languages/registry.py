"""Language Registry mapping and detection logic. Stage 12."""
from pathlib import Path
from typing import List, Optional
from impact_engine.languages.models import LanguageProfile
from impact_engine.languages.semantics import (
    CSHARP_SEMANTICS,
    GO_SEMANTICS,
    JAVA_SEMANTICS,
    JAVASCRIPT_SEMANTICS,
    PYTHON_SEMANTICS,
    TYPESCRIPT_SEMANTICS,
)

# Pre-defined profiles
PYTHON_PROFILE = LanguageProfile(
    language_id="python",
    display_name="Python",
    file_extensions={".py"},
    package_manifest_files={"pyproject.toml", "requirements.txt"},
    standard_library_modules={
        "os", "sys", "pathlib", "json", "ast", "typing", "dataclasses",
        "collections", "functools", "itertools", "enum", "abc", "math",
        "re", "datetime", "hashlib", "tempfile", "shutil", "urllib", "time"
    },
    default_extractor_id="python_ast",
    semantic_provider=PYTHON_SEMANTICS,
)

JAVASCRIPT_PROFILE = LanguageProfile(
    language_id="javascript",
    display_name="JavaScript",
    file_extensions={".js", ".jsx"},
    package_manifest_files={"package.json"},
    standard_library_modules={"fs", "path", "os", "crypto", "http", "https"},
    default_extractor_id="tree_sitter",
    semantic_provider=JAVASCRIPT_SEMANTICS,
)

TYPESCRIPT_PROFILE = LanguageProfile(
    language_id="typescript",
    display_name="TypeScript",
    file_extensions={".ts", ".tsx"},
    package_manifest_files={"package.json", "tsconfig.json"},
    standard_library_modules={"fs", "path", "os", "crypto", "http", "https"},
    default_extractor_id="tree_sitter",
    semantic_provider=TYPESCRIPT_SEMANTICS,
)

GO_PROFILE = LanguageProfile(
    language_id="go",
    display_name="Go",
    file_extensions={".go"},
    package_manifest_files={"go.mod"},
    standard_library_modules={"fmt", "os", "io", "net/http", "time", "sync", "encoding/json"},
    default_extractor_id="tree_sitter",
    semantic_provider=GO_SEMANTICS,
)

JAVA_PROFILE = LanguageProfile(
    language_id="java",
    display_name="Java",
    file_extensions={".java"},
    package_manifest_files={"pom.xml", "build.gradle"},
    standard_library_modules={"java.lang", "java.util", "java.io", "java.net", "java.nio"},
    default_extractor_id="tree_sitter",
    semantic_provider=JAVA_SEMANTICS,
)

CSHARP_PROFILE = LanguageProfile(
    language_id="csharp",
    display_name="C#",
    file_extensions={".cs"},
    package_manifest_files={".csproj", ".sln", ".slnx", "directory.build.props", "global.json"},
    standard_library_modules={"System", "Microsoft", "mscorlib", "netstandard"},
    default_extractor_id="csharp_structural",
    semantic_provider=CSHARP_SEMANTICS,
)

PROFILES = {
    "python": PYTHON_PROFILE,
    "javascript": JAVASCRIPT_PROFILE,
    "typescript": TYPESCRIPT_PROFILE,
    "go": GO_PROFILE,
    "java": JAVA_PROFILE,
    "csharp": CSHARP_PROFILE,
}


def list_language_profiles() -> List[LanguageProfile]:
    return list(PROFILES.values())


def get_language_profile(language_id: str) -> Optional[LanguageProfile]:
    return PROFILES.get(language_id)


def detect_languages(project_path: str | Path) -> List[str]:
    # ``iter_project_files`` resolves yielded paths.  Resolve the root as
    # well, otherwise a perfectly normal relative CLI argument makes
    # ``Path.relative_to`` compare absolute and relative paths.
    root = Path(project_path).expanduser().resolve()
    if not root.exists():
        return []

    found_extensions = set()
    found_manifests = set()

    # If it is a single file, check extension
    if root.is_file():
        found_extensions.add(root.suffix.lower())
    else:
        # Walk directories, ignoring standard build/venv directories
        from impact_engine.scope import iter_project_files
        for p in iter_project_files(root):
            parts = p.relative_to(root).parts
            if any(part.startswith(".") or part == "__pycache__" or part == "venv" or part == "env" or part == "node_modules" for part in parts):
                continue
            if p.is_file():
                found_extensions.add(p.suffix.lower())
                found_manifests.add(p.name.lower())

    detected = []
    for lang_id, profile in PROFILES.items():
        # A language is detected if any of its extensions or manifest files are present
        ext_match = any(ext in found_extensions for ext in profile.file_extensions)
        manifest_match = any(manifest.lower() in found_manifests for manifest in profile.package_manifest_files)
        if ext_match or manifest_match:
            detected.append(lang_id)

    return sorted(detected)
