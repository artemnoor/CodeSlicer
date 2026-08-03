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
    CPP_SEMANTICS,
    RUST_SEMANTICS,
    KOTLIN_SEMANTICS,
    PHP_SEMANTICS,
    RUBY_SEMANTICS,
    HTML_SEMANTICS,
    CSS_SEMANTICS,
    VUE_SEMANTICS,
    SVELTE_SEMANTICS,
    ASTRO_SEMANTICS,
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
    file_extensions={".js", ".jsx", ".mjs", ".cjs"},
    package_manifest_files={"package.json"},
    standard_library_modules={"fs", "path", "os", "crypto", "http", "https"},
    default_extractor_id="tree_sitter",
    semantic_provider=JAVASCRIPT_SEMANTICS,
)

TYPESCRIPT_PROFILE = LanguageProfile(
    language_id="typescript",
    display_name="TypeScript",
    file_extensions={".ts", ".tsx", ".mts", ".cts"},
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

CPP_PROFILE = LanguageProfile(
    language_id="cpp",
    display_name="C/C++",
    file_extensions={".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"},
    package_manifest_files={"CMakeLists.txt", "CMakePresets.json", "compile_commands.json", "meson.build", "BUILD", "BUILD.bazel", "WORKSPACE", "WORKSPACE.bazel", "Makefile", "build.ninja", ".clangd", ".clang-tidy"},
    standard_library_modules=set(),
    default_extractor_id="tree_sitter",
    semantic_provider=CPP_SEMANTICS,
)

RUST_PROFILE = LanguageProfile(
    language_id="rust", display_name="Rust", file_extensions={".rs"},
    package_manifest_files={"cargo.toml"}, standard_library_modules={"std", "core", "alloc"},
    default_extractor_id="tree_sitter", semantic_provider=RUST_SEMANTICS,
)

KOTLIN_PROFILE = LanguageProfile(
    language_id="kotlin", display_name="Kotlin", file_extensions={".kt", ".kts"},
    package_manifest_files={"build.gradle.kts"}, standard_library_modules={"kotlin", "java"},
    default_extractor_id="tree_sitter", semantic_provider=KOTLIN_SEMANTICS,
)

PHP_PROFILE = LanguageProfile(
    language_id="php", display_name="PHP", file_extensions={".php"},
    package_manifest_files={"composer.json"}, standard_library_modules=set(),
    default_extractor_id="tree_sitter", semantic_provider=PHP_SEMANTICS,
)

RUBY_PROFILE = LanguageProfile(
    language_id="ruby", display_name="Ruby", file_extensions={".rb"},
    package_manifest_files={"gemfile", "gemspec"}, standard_library_modules=set(),
    default_extractor_id="tree_sitter", semantic_provider=RUBY_SEMANTICS,
)

HTML_PROFILE = LanguageProfile(
    language_id="html", display_name="HTML", file_extensions={".html", ".htm", ".xhtml"},
    package_manifest_files=set(), standard_library_modules=set(), default_extractor_id="tree_sitter",
    semantic_provider=HTML_SEMANTICS,
)

CSS_PROFILE = LanguageProfile(
    language_id="css", display_name="CSS", file_extensions={".css", ".scss", ".sass", ".less"},
    package_manifest_files=set(), standard_library_modules=set(), default_extractor_id="tree_sitter",
    semantic_provider=CSS_SEMANTICS,
)

VUE_PROFILE = LanguageProfile(
    language_id="vue", display_name="Vue", file_extensions={".vue"},
    package_manifest_files={"package.json"}, standard_library_modules=set(), default_extractor_id="tree_sitter",
    semantic_provider=VUE_SEMANTICS,
)

SVELTE_PROFILE = LanguageProfile(
    language_id="svelte", display_name="Svelte", file_extensions={".svelte"},
    package_manifest_files={"package.json"}, standard_library_modules=set(), default_extractor_id="tree_sitter",
    semantic_provider=SVELTE_SEMANTICS,
)

ASTRO_PROFILE = LanguageProfile(
    language_id="astro", display_name="Astro", file_extensions={".astro"},
    package_manifest_files={"package.json"}, standard_library_modules=set(), default_extractor_id="tree_sitter",
    semantic_provider=ASTRO_SEMANTICS,
)

PROFILES = {
    "python": PYTHON_PROFILE,
    "javascript": JAVASCRIPT_PROFILE,
    "typescript": TYPESCRIPT_PROFILE,
    "go": GO_PROFILE,
    "java": JAVA_PROFILE,
    "csharp": CSHARP_PROFILE,
    "cpp": CPP_PROFILE,
    "rust": RUST_PROFILE,
    "kotlin": KOTLIN_PROFILE,
    "php": PHP_PROFILE,
    "ruby": RUBY_PROFILE,
    "html": HTML_PROFILE,
    "css": CSS_PROFILE,
    "vue": VUE_PROFILE,
    "svelte": SVELTE_PROFILE,
    "astro": ASTRO_PROFILE,
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
