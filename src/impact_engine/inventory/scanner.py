"""Project Inventory scanner logic. Stage 12."""
import ast
import json
import re
import sys
try:
    import tomllib
except ImportError:
    # Fallback for Python versions without tomllib, though v3.11 is baseline
    import pip._vendor.tomli as tomllib
from pathlib import Path
from typing import List, Set
from impact_engine.languages.registry import detect_languages, get_language_profile
from impact_engine.inventory.models import ProjectInventory


def parse_dependency_name(d: str) -> str:
    # Split on version specifiers or environment markers
    name = re.split(r"[>=<!;~@\[\s]", d)[0].strip()
    return name


def parse_pyproject(path: Path) -> List[str]:
    deps = set()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        
        project_sec = data.get("project", {})
        # Project main dependencies
        for d in project_sec.get("dependencies", []):
            name = parse_dependency_name(d)
            if name:
                deps.add(name)
        # Optional dependencies (dev, test, etc.)
        for group, group_deps in project_sec.get("optional-dependencies", {}).items():
            for d in group_deps:
                name = parse_dependency_name(d)
                if name:
                    deps.add(name)
                    
        # Poetry dependencies
        poetry_sec = data.get("tool", {}).get("poetry", {})
        for name in poetry_sec.get("dependencies", {}).keys():
            if name.lower() != "python":
                deps.add(name)
        # Poetry groups
        for group, group_sec in poetry_sec.get("group", {}).items():
            for name in group_sec.get("dependencies", {}).keys():
                deps.add(name)
    except Exception:
        pass
    return sorted(list(deps))


def parse_pyproject_groups(path: Path) -> tuple[List[str], List[str]]:
    """Return runtime and development dependencies separately."""
    runtime: set[str] = set()
    dev: set[str] = set()
    dev_markers = ("dev", "test", "lint", "format", "docs", "quality", "type")
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        project = data.get("project", {})
        for value in project.get("dependencies", []) or []:
            name = parse_dependency_name(value)
            if name:
                runtime.add(name)
        for group, values in (project.get("optional-dependencies", {}) or {}).items():
            target = dev if any(marker in str(group).lower() for marker in dev_markers) else runtime
            for value in values or []:
                name = parse_dependency_name(value)
                if name:
                    target.add(name)
        poetry = data.get("tool", {}).get("poetry", {})
        for name in (poetry.get("dependencies", {}) or {}):
            if str(name).lower() != "python":
                runtime.add(str(name))
        for group, section in (poetry.get("group", {}) or {}).items():
            target = dev if any(marker in str(group).lower() for marker in dev_markers) else runtime
            for name in (section.get("dependencies", {}) or {}):
                target.add(str(name))
    except Exception:
        pass
    return sorted(runtime), sorted(dev)


def parse_requirements(path: Path) -> List[str]:
    deps = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name = parse_dependency_name(line)
            if name:
                deps.add(name)
    except Exception:
        pass
    return sorted(list(deps))


def parse_package_json(path: Path) -> List[str]:
    deps = set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ["dependencies", "devDependencies", "peerDependencies"]:
            if key in data and isinstance(data[key], dict):
                for name in data[key].keys():
                    deps.add(name)
    except Exception:
        pass
    return sorted(list(deps))


def parse_package_json_groups(path: Path) -> tuple[List[str], List[str]]:
    runtime = set()
    dev = set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ["dependencies", "peerDependencies"]:
            if isinstance(data.get(key), dict):
                runtime.update(data[key].keys())
        if isinstance(data.get("devDependencies"), dict):
            dev.update(data["devDependencies"].keys())
    except Exception:
        pass
    return sorted(runtime), sorted(dev)


def parse_package_json_aliases(path: Path) -> List[str]:
    aliases = set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        imports = data.get("imports", {})
        if isinstance(imports, dict):
            for alias in imports:
                if str(alias).startswith("#"):
                    aliases.add(str(alias).split("*", 1)[0].rstrip("/"))
    except Exception:
        pass
    return sorted(aliases)


def parse_go_mod(path: Path) -> List[str]:
    direct, _ = parse_go_mod_groups(path)
    return direct


def parse_go_mod_groups(path: Path) -> tuple[List[str], List[str]]:
    """Return direct and explicitly indirect Go module requirements."""
    deps = set()
    indirect = set()
    try:
        content = path.read_text(encoding="utf-8")
        in_block = False
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("require ("):
                in_block = True
                continue
            if line == ")":
                in_block = False
                continue
            if in_block:
                parts = line.split()
                if parts:
                    (indirect if "// indirect" in line else deps).add(parts[0])
            elif line.startswith("require "):
                parts = line[8:].strip().split()
                if parts:
                    deps.add(parts[0])
    except Exception:
        pass
    return sorted(deps), sorted(indirect)


def parse_go_module_name(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("module "):
                return line.split(None, 1)[1].strip()
    except Exception:
        pass
    return None


def parse_pom_xml(path: Path) -> List[str]:
    deps = set()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for block in re.findall(r"<dependency>(.*?)</dependency>", text, flags=re.DOTALL):
            group = re.search(r"<groupId>\s*([^<\s]+)\s*</groupId>", block)
            artifact = re.search(r"<artifactId>\s*([^<\s]+)\s*</artifactId>", block)
            if group and artifact:
                deps.add(f"{group.group(1)}:{artifact.group(1)}")
            elif group:
                deps.add(group.group(1))
    except Exception:
        pass
    return sorted(deps)


def parse_build_gradle(path: Path) -> List[str]:
    deps = set()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"['\"]([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):[^'\"]+['\"]", text):
            deps.add(f"{match.group(1)}:{match.group(2)}")
    except Exception:
        pass
    return sorted(deps)


def _add_map_value(target: dict[str, set[str]], ecosystem: str, value: str) -> None:
    if value:
        target.setdefault(ecosystem, set()).add(value)


def _is_ignored_path(parts: tuple[str, ...]) -> bool:
    ignored = {"__pycache__", "venv", "env", "node_modules", "dist", "build", "target", ".next", "coverage"}
    return any(part.startswith(".") or part in ignored for part in parts)


def parse_tsconfig_aliases(path: Path) -> List[str]:
    aliases = set()
    try:
        # tsconfig is JSONC in practice; comments are valid there even though
        # the standard JSON parser rejects them.
        content = path.read_text(encoding="utf-8")
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        content = re.sub(r"(^|\s)//.*$", r"\1", content, flags=re.MULTILINE)
        data = json.loads(content)
        paths = data.get("compilerOptions", {}).get("paths", {})
        if isinstance(paths, dict):
            for alias in paths:
                clean = str(alias).split("*", 1)[0].rstrip("/")
                if clean:
                    aliases.add(clean)
    except Exception:
        pass
    return sorted(aliases)


def parse_vite_aliases(path: Path) -> List[str]:
    aliases = set()
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        # Covers the common resolve.alias object form without pretending to
        # execute arbitrary Vite configuration code.
        for match in re.finditer(r"[\"']([^\"']+)[\"']\s*:", content):
            alias = match.group(1).strip()
            if alias.startswith("@"):
                aliases.add(alias.rstrip("/"))
    except Exception:
        pass
    return sorted(aliases)


def parse_java_package(content: str) -> str | None:
    match = re.search(r"^\s*package\s+([A-Za-z_][\w.]*)\s*;", content, flags=re.MULTILINE)
    return match.group(1) if match else None


def scan_project_inventory(project_path: str | Path) -> ProjectInventory:
    root = Path(project_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Project directory {project_path} does not exist")

    # 1. Detect languages
    languages = detect_languages(root)

    # 2. Collect files and find local modules
    files = []
    py_files = []
    js_files = []
    ts_files = []
    go_files = []
    java_files = []
    manifests = []
    local_modules = set()
    local_modules_by_ecosystem: dict[str, set[str]] = {}
    java_local_packages: set[str] = set()
    classes_count = 0
    methods_count = 0
    loc = 0

    # Scan project files
    for p in root.rglob("*"):
        parts = p.relative_to(root).parts
        if _is_ignored_path(parts):
            continue
            
        if p.is_file():
            rel_path = str(p.relative_to(root).as_posix())
            files.append(rel_path)

            suffix = p.suffix.lower()
            if suffix in [".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java"]:
                try:
                    content_for_counts = p.read_text(encoding="utf-8")
                    loc += len([line for line in content_for_counts.splitlines() if line.strip()])
                except Exception:
                    content_for_counts = ""
            if suffix == ".py":
                py_files.append(p)
                if parts:
                    _add_map_value(local_modules_by_ecosystem, "python", parts[0].rsplit(".", 1)[0])
                    if len(parts) >= 3 and parts[-2] != "__pycache__" and parts[0] == "src":
                        _add_map_value(local_modules_by_ecosystem, "python", parts[1])
                    for parent in p.parents:
                        if parent == root or root not in parent.parents:
                            continue
                        if (parent / "__init__.py").exists():
                            _add_map_value(local_modules_by_ecosystem, "python", parent.name)
                if content_for_counts:
                    try:
                        count_tree = ast.parse(content_for_counts)
                        for ast_node in ast.walk(count_tree):
                            if isinstance(ast_node, ast.ClassDef):
                                classes_count += 1
                            elif isinstance(ast_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                methods_count += 1
                    except Exception:
                        pass
            elif suffix in [".js", ".jsx"]:
                js_files.append(p)
                if parts:
                    _add_map_value(local_modules_by_ecosystem, "javascript", parts[0].rsplit(".", 1)[0])
                classes_count += len(re.findall(r"\bclass\s+[A-Za-z_$][\w$]*", content_for_counts))
                methods_count += len(re.findall(r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(", content_for_counts))
            elif suffix in [".ts", ".tsx"]:
                ts_files.append(p)
                if parts:
                    _add_map_value(local_modules_by_ecosystem, "typescript", parts[0].rsplit(".", 1)[0])
                classes_count += len(re.findall(r"\bclass\s+[A-Za-z_$][\w$]*", content_for_counts))
                methods_count += len(re.findall(r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(", content_for_counts))
            elif suffix == ".go":
                go_files.append(p)
                if len(parts) > 1:
                    _add_map_value(local_modules_by_ecosystem, "go", parts[0])
                methods_count += len(re.findall(r"\bfunc\s+(?:\([^)]*\)\s*)?[A-Za-z_]\w*\s*\(", content_for_counts))
            elif suffix == ".java":
                java_files.append(p)
                if len(parts) > 1:
                    _add_map_value(local_modules_by_ecosystem, "java", parts[0])
                classes_count += len(re.findall(r"\bclass\s+[A-Za-z_]\w*", content_for_counts))
                methods_count += len(re.findall(r"(?:public|private|protected|static|final|synchronized|\s)+[\w<>\[\]]+\s+[A-Za-z_]\w*\s*\(", content_for_counts))
                package_name = parse_java_package(content_for_counts)
                if package_name:
                    java_local_packages.add(package_name)
                    package_parts = package_name.split(".")
                    for size in range(2, len(package_parts) + 1):
                        _add_map_value(local_modules_by_ecosystem, "java", ".".join(package_parts[:size]))

            # Determine local modules
            if parts:
                top_part = parts[0]
                if top_part.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java")):
                    local_modules.add(top_part.rsplit(".", 1)[0])
                else:
                    local_modules.add(top_part)

    # Filter files to sort them
    files.sort()

    # 3. Detect manifests and declared dependencies
    declared_dependencies = set()
    transitive_dependencies = set()
    declared_dependencies_by_ecosystem: dict[str, set[str]] = {}
    transitive_dependencies_by_ecosystem: dict[str, set[str]] = {}
    dev_dependencies_by_ecosystem: dict[str, set[str]] = {}
    
    # Manifest filenames mapped to parser functions
    manifest_parsers = {
        "pyproject.toml": ("python", parse_pyproject),
        "requirements.txt": ("python", parse_requirements),
        "package.json": ("typescript" if "typescript" in languages else "javascript", parse_package_json),
        "go.mod": ("go", parse_go_mod),
        "pom.xml": ("java", parse_pom_xml),
        "build.gradle": ("java", parse_build_gradle),
        "tsconfig.json": ("typescript", lambda path: []),
    }

    for m_path in root.rglob("*"):
        if not m_path.is_file():
            continue
        parts = m_path.relative_to(root).parts
        if _is_ignored_path(parts):
            continue
        parser_info = manifest_parsers.get(m_path.name)
        if not parser_info:
            continue
        ecosystem, parser = parser_info
        rel_manifest = m_path.relative_to(root).as_posix()
        manifests.append(rel_manifest)
        if m_path.name == "package.json":
            runtime_deps, dev_deps = parse_package_json_groups(m_path)
            deps = set(runtime_deps) | set(dev_deps)
            dev_dependencies_by_ecosystem.setdefault(ecosystem, set()).update(dev_deps)
            for alias in parse_package_json_aliases(m_path):
                _add_map_value(local_modules_by_ecosystem, ecosystem, alias)
        elif m_path.name == "pyproject.toml":
            runtime_deps, dev_deps = parse_pyproject_groups(m_path)
            deps = set(runtime_deps) | set(dev_deps)
            dev_dependencies_by_ecosystem.setdefault(ecosystem, set()).update(dev_deps)
        elif m_path.name == "go.mod":
            deps, indirect_deps = parse_go_mod_groups(m_path)
            transitive_dependencies.update(indirect_deps)
            transitive_dependencies_by_ecosystem.setdefault(ecosystem, set()).update(indirect_deps)
        else:
            deps = set(parser(m_path))
        declared_dependencies.update(deps)
        declared_dependencies_by_ecosystem.setdefault(ecosystem, set()).update(deps)
        if m_path.name == "tsconfig.json":
            for alias in parse_tsconfig_aliases(m_path):
                _add_map_value(local_modules_by_ecosystem, "typescript", alias)
                _add_map_value(local_modules_by_ecosystem, "javascript", alias)
        if m_path.name.startswith("vite.config."):
            for alias in parse_vite_aliases(m_path):
                _add_map_value(local_modules_by_ecosystem, "typescript", alias)
                _add_map_value(local_modules_by_ecosystem, "javascript", alias)
        if m_path.name == "go.mod":
            module_name = parse_go_module_name(m_path)
            if module_name:
                _add_map_value(local_modules_by_ecosystem, "go", module_name)

    manifests.sort()

    # 4. Extract external imports
    external_imports = set()
    external_imports_by_ecosystem: dict[str, set[str]] = {}
    
    # We gather stdlib modules for all detected languages to ignore them
    stdlib_ignored = set()
    for lang in languages:
        profile = get_language_profile(lang)
        if profile:
            stdlib_ignored.update(profile.standard_library_modules)

    # Standard python stdlib future is ignored
    stdlib_ignored.add("__future__")
    stdlib_ignored.update(getattr(sys, "stdlib_module_names", set()) or set())

    # Collect Python imports
    for f in py_files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        imp_root = name.name.split(".")[0]
                        local_python = local_modules | local_modules_by_ecosystem.get("python", set())
                        if imp_root not in local_python and imp_root not in stdlib_ignored:
                            external_imports.add(imp_root)
                            _add_map_value(external_imports_by_ecosystem, "python", imp_root)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        if node.level > 0:  # relative import
                            continue
                        imp_root = node.module.split(".")[0]
                        local_python = local_modules | local_modules_by_ecosystem.get("python", set())
                        if imp_root not in local_python and imp_root not in stdlib_ignored:
                            external_imports.add(imp_root)
                            _add_map_value(external_imports_by_ecosystem, "python", imp_root)
        except Exception:
            pass

    # Collect simple ES6 / CommonJS imports for JS/TS
    js_ts_import_regex = re.compile(
        r'(?:import\s+(?:(?:type\s+)?(?:\*\s+as\s+)?[\w${}\s,*]+?\s+from\s+)?[\'"]([^\'"]+)[\'"])|'
        r'(?:require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\))|'
        r'(?:from\s+[\'"]([^\'"]+)[\'"])'
    )
    for f in js_files + ts_files:
        try:
            content = f.read_text(encoding="utf-8")
            for match in js_ts_import_regex.finditer(content):
                imp = match.group(1) or match.group(2) or match.group(3)
                if imp and not imp.startswith("."):
                    if imp.startswith("@"):
                        imp_parts = imp.split("/")
                        imp_root = "/".join(imp_parts[:2]) if len(imp_parts) >= 2 else imp
                    else:
                        imp_root = imp.split("/")[0]
                    local_js = local_modules | local_modules_by_ecosystem.get(ecosystem, set())
                    if imp_root not in local_js and imp_root not in stdlib_ignored:
                        external_imports.add(imp_root)
                        ecosystem = "typescript" if f.suffix.lower() in [".ts", ".tsx"] else "javascript"
                        _add_map_value(external_imports_by_ecosystem, ecosystem, imp_root)
        except Exception:
            pass

    go_import_block_re = re.compile(r'import\s*\((.*?)\)', re.DOTALL)
    go_import_line_re = re.compile(r'import\s+(?:[.\w]+\s+)?["`]([^"`]+)["`]')
    for f in go_files:
        try:
            content = f.read_text(encoding="utf-8")
            imports = []
            for block in go_import_block_re.findall(content):
                imports.extend(re.findall(r'(?:[.\w]+\s+)?["`]([^"`]+)["`]', block))
            imports.extend(go_import_line_re.findall(content))
            for imp in imports:
                go_local = local_modules | local_modules_by_ecosystem.get("go", set())
                go_stdlib = "." not in imp.split("/", 1)[0]
                if imp not in stdlib_ignored and imp not in go_local and not go_stdlib:
                    external_imports.add(imp)
                    _add_map_value(external_imports_by_ecosystem, "go", imp)
        except Exception:
            pass

    java_import_re = re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z_][\w.]*)(?:\.\*)?\s*;", re.MULTILINE)
    for f in java_files:
        try:
            content = f.read_text(encoding="utf-8")
            for imp in java_import_re.findall(content):
                is_local = any(imp == prefix or imp.startswith(prefix + ".") for prefix in java_local_packages)
                if not imp.startswith(("java.", "javax.")) and not is_local:
                    external_imports.add(imp)
                    _add_map_value(external_imports_by_ecosystem, "java", imp)
        except Exception:
            pass

    return ProjectInventory(
        root_path=str(root.as_posix()),
        files=files,
        languages=languages,
        package_manifests=manifests,
        declared_dependencies=sorted(list(declared_dependencies)),
        transitive_dependencies=sorted(list(transitive_dependencies)),
        external_imports=sorted(list(external_imports)),
        local_modules=sorted(list(local_modules)),
        declared_dependencies_by_ecosystem={k: sorted(v) for k, v in declared_dependencies_by_ecosystem.items()},
        transitive_dependencies_by_ecosystem={k: sorted(v) for k, v in transitive_dependencies_by_ecosystem.items()},
        dev_dependencies_by_ecosystem={k: sorted(v) for k, v in dev_dependencies_by_ecosystem.items()},
        external_imports_by_ecosystem={k: sorted(v) for k, v in external_imports_by_ecosystem.items()},
        local_modules_by_ecosystem={k: sorted(v) for k, v in local_modules_by_ecosystem.items()},
        files_count=len(files),
        classes_count=classes_count,
        methods_count=methods_count,
        loc=loc
    )


def scan_project(project_path: str | Path) -> ProjectInventory:
    """Alias for scan_project_inventory for backward compatibility."""
    return scan_project_inventory(project_path)
