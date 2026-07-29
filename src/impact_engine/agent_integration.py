"""Safe local installation of CodeSlicer skills and MCP registrations.

This module deliberately contains no task-routing or analysis logic.  It only
owns packaged skill assets and the small, client-specific configuration entries
needed to expose the local ``impact-engine-mcp`` stdio server.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.resources
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable, Iterable

import yaml


SKILLS = ("codeslicer-impact-analysis", "graphify-architecture-analysis")
STATE_VERSION = 1
_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class ClientAdapter:
    id: str
    display_name: str
    aliases: tuple[str, ...]
    integration: str
    project_skills: str | None
    user_skills: str | None
    project_mcp: str | None
    user_mcp: str | None
    mcp_key: str = "mcpServers"
    support: str = "experimental"
    last_verified: str | None = None
    limitations: str = ""
    executable: str | None = None
    mcp_format: str = "jsonc"


# Paths are relative to the selected project/home.  A non-verified adapter is
# visible to users but is never described as having a guaranteed contract.
CLIENTS: tuple[ClientAdapter, ...] = (
    ClientAdapter("codex", "Codex CLI / IDE", ("openai-codex", "codex-cli", "codex-ide"), "native-skill", ".agents/skills", ".agents/skills", None, ".codex/config.toml", support="verified", last_verified="2026-07-28", executable="codex", limitations="Project MCP is CLI-version dependent; user MCP uses a comment-preserving config.toml fallback (Codex CLI also supports `mcp add`).", mcp_format="toml"),
    ClientAdapter("claude", "Claude Code", ("claude-code", "anthropic-claude"), "native-skill", ".claude/skills", ".claude/skills", ".mcp.json", None, executable="claude"),
    ClientAdapter("cursor", "Cursor IDE", ("cursor-ide", "cursor-cli"), "rule-adapter", ".cursor/rules", None, ".cursor/mcp.json", ".cursor/mcp.json", executable="cursor", limitations="Skills are emitted as separate context-triggered .mdc rules."),
    ClientAdapter("windsurf", "Windsurf / Cascade", ("cascade", "codeium"), "native-skill", ".windsurf/skills", ".codeium/windsurf/skills", None, ".codeium/windsurf/mcp_config.json", executable="windsurf"),
    ClientAdapter("qwen", "Qwen Code", ("qwen-code", "qwen-cli"), "native-skill", ".qwen/skills", ".qwen/skills", None, None, executable="qwen"),
    ClientAdapter("kilo", "Kilo Code", ("kilo-code", "kilocode"), "native-skill", ".kilo/skills", ".kilo/skills", ".kilo/kilo.jsonc", ".config/kilo/kilo.jsonc", executable="kilo"),
    ClientAdapter("kiro", "Kiro IDE", ("kiro-ide", "kiro-cli"), "instruction-adapter", ".kiro/steering", ".kiro/steering", ".kiro/settings/mcp.json", ".kiro/settings/mcp.json", executable="kiro-cli", limitations="Uses separate steering files because native skills are not assumed."),
    ClientAdapter("qoder", "Qoder IDE", ("qoder-ide", "qoder-cli", "qodercli"), "native-skill", ".qoder/skills", ".qoder/skills", ".qoder/settings.local.json", ".qoder/settings.json", executable="qodercli"),
    ClientAdapter("copilot", "GitHub Copilot CLI", ("github-copilot", "copilot-cli"), "shared-skill", ".agents/skills", ".agents/skills", ".mcp.json", ".copilot/mcp-config.json", executable="copilot"),
    ClientAdapter("gemini", "Gemini CLI", ("gemini-cli", "google-gemini"), "shared-skill", ".gemini/skills", ".gemini/skills", ".gemini/settings.json", ".gemini/settings.json", executable="gemini"),
    ClientAdapter("cline", "Cline", (), "instruction-adapter", None, None, None, None, support="unsupported", limitations="No safe documented automatic skill or MCP target is registered by this installer."),
    ClientAdapter("opencode", "OpenCode", (), "native-skill", ".opencode/skills", ".config/opencode/skills", ".opencode/mcp.json", ".config/opencode/mcp.json", executable="opencode"),
    ClientAdapter("zed", "Zed", (), "instruction-adapter", None, None, ".zed/settings.json", ".config/zed/settings.json", executable="zed"),
    ClientAdapter("junie", "Junie", (), "instruction-adapter", ".junie", None, ".junie/mcp/mcp.json", None),
    ClientAdapter("codebuddy", "CodeBuddy", (), "instruction-adapter", None, None, None, None, support="unsupported", limitations="No safe documented automatic skill or MCP target is registered by this installer."),
    ClientAdapter("kodik", "Kodik IDE", ("kodik-ide", "kodik-cli"), "native-skill", ".kodik/skills", "Documents/Kodik/Skills", None, "User/globalStorage/kodik.chat/settings/mcp.json", mcp_key="servers", support="verified", last_verified="2026-07-28", executable="kodik", limitations="MCP is a user-level JSONC file in Kodik globalStorage; installer locates an existing file and never enables auto-approve."),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _home(home: str | Path | None = None) -> Path:
    return Path(home).expanduser().resolve() if home else Path.home().resolve()


def _state_path(project: Path, scope: str, home: Path) -> Path:
    return (project / ".codeslicer" / "agent-install.json") if scope == "project" else (home / ".codeslicer" / "agent-install.json")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, prefix=f".{path.name}.") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def bundled_skills() -> dict[str, dict[str, Any]]:
    """Read and validate only the two supported assets from the installed wheel."""
    root = importlib.resources.files("impact_engine.agent_skills")
    result: dict[str, dict[str, Any]] = {}
    for name in SKILLS:
        asset = root.joinpath(name, "SKILL.md")
        if not asset.is_file():
            raise FileNotFoundError(f"bundled CodeSlicer skill is missing: {name}/SKILL.md")
        raw = asset.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            raise ValueError(f"bundled skill {name} has no YAML frontmatter")
        _prefix, frontmatter, _body = raw.split("---\n", 2)
        metadata = yaml.safe_load(frontmatter)
        if not isinstance(metadata, dict) or metadata.get("name") != name or not _SKILL_NAME.fullmatch(name):
            raise ValueError(f"bundled skill {name} has invalid or mismatched frontmatter name")
        result[name] = {"name": name, "text": raw, "source_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "metadata": metadata}
    return result


def client_catalog() -> list[dict[str, Any]]:
    return [{
        "id": item.id, "display_name": item.display_name, "aliases": list(item.aliases), "status": item.support,
        "integration": item.integration, "project_skills": bool(item.project_skills), "user_skills": bool(item.user_skills),
        "project_mcp": bool(item.project_mcp), "user_mcp": bool(item.user_mcp), "last_verified": item.last_verified,
        "limitations": item.limitations,
    } for item in CLIENTS]


def resolve_client(value: str) -> ClientAdapter:
    token = value.strip().lower()
    for item in CLIENTS:
        if token == item.id or token in item.aliases:
            return item
    raise ValueError(f"unsupported AI client: {value}")


def _evidence(path: Path, kind: str) -> dict[str, str]:
    return {"kind": kind, "path": str(path)}


def _known_kodik_mcp_paths(home: Path) -> list[Path]:
    # Kodik deliberately documents the app globalStorage suffix but platform
    # roots differ; inspect existing local files only, never create a guessed one.
    roots = [home / "AppData/Roaming", home / ".config", home / "Library/Application Support"]
    return [root / "User/globalStorage/kodik.chat/settings/mcp.json" for root in roots]


def detect_clients(project_path: str | Path = ".", *, home: str | Path | None = None) -> list[dict[str, Any]]:
    project = Path(project_path).expanduser().resolve(); user_home = _home(home)
    detected: list[dict[str, Any]] = []
    for adapter in CLIENTS:
        evidence: list[dict[str, str]] = []
        executable = shutil.which(adapter.executable) if adapter.executable else None
        if executable:
            evidence.append(_evidence(Path(executable), "executable"))
        if adapter.project_skills and (project / adapter.project_skills).is_dir():
            evidence.append(_evidence(project / adapter.project_skills, "workspace_directory"))
        if adapter.project_mcp and (project / adapter.project_mcp).is_file():
            evidence.append(_evidence(project / adapter.project_mcp, "workspace_config"))
        if adapter.id == "kodik":
            for path in _known_kodik_mcp_paths(user_home):
                if path.is_file(): evidence.append(_evidence(path, "user_config"))
        elif adapter.user_mcp and (user_home / adapter.user_mcp).is_file():
            evidence.append(_evidence(user_home / adapter.user_mcp, "user_config"))
        elif adapter.user_skills and (user_home / adapter.user_skills).is_dir():
            evidence.append(_evidence(user_home / adapter.user_skills, "user_directory"))
        confidence = "high" if executable and any(item["kind"].startswith("workspace") for item in evidence) else ("medium" if executable or len(evidence) > 1 else ("low" if evidence else "none"))
        detected.append({"id": adapter.id, "display_name": adapter.display_name, "detected": bool(evidence), "confidence": confidence, "evidence": evidence})
    return detected


def mcp_launcher() -> dict[str, Any]:
    # PATH can point at a different global CodeSlicer installation than the
    # interpreter running this CLI.  Prefer the console script beside this
    # interpreter, then use ``-m`` from the same interpreter as a stable
    # wheel/editable/pipx fallback.
    interpreter_dir = Path(sys.executable).parent
    scripts = interpreter_dir if interpreter_dir.name.lower() in {"scripts", "bin"} else interpreter_dir / ("Scripts" if os.name == "nt" else "bin")
    executable = scripts / ("impact-engine-mcp.exe" if os.name == "nt" else "impact-engine-mcp")
    return {"command": str(executable) if executable.is_file() else sys.executable, "args": [] if executable.is_file() else ["-m", "impact_engine.mcp.server"]}


def _skill_destination(adapter: ClientAdapter, project: Path, scope: str, home: Path, skill: str) -> Path:
    root = adapter.project_skills if scope == "project" else adapter.user_skills
    if not root:
        raise ValueError(f"{adapter.display_name} has no {scope} skill destination")
    base = project if scope == "project" else home
    suffix = ".mdc" if adapter.integration == "rule-adapter" else (".md" if adapter.integration == "instruction-adapter" else "SKILL.md")
    return base / root / (f"{skill}{suffix}" if suffix != "SKILL.md" else f"{skill}/SKILL.md")


def _skill_scope(adapter: ClientAdapter, requested_scope: str) -> tuple[str | None, str | None]:
    """Choose a safe skills location without making one IDE break all others.

    Cursor deliberately exposes project rules rather than a user-level skills
    directory.  Its rules are still useful from the one-command setup, but
    must be written into the selected workspace.  Some MCP-only adapters have
    no skills target at all; they can still receive their MCP registration.
    """
    configured = adapter.project_skills if requested_scope == "project" else adapter.user_skills
    if configured:
        return requested_scope, None
    if requested_scope == "user" and adapter.project_skills:
        return (
            "project",
            f"{adapter.display_name} has no user skill destination; installed its project-level rules in {adapter.project_skills}.",
        )
    return None, f"{adapter.display_name} has no {requested_scope} skill destination; skipped CodeSlicer skills for this IDE."


def _render_skill(adapter: ClientAdapter, skill: dict[str, Any]) -> str:
    if adapter.integration != "rule-adapter":
        return str(skill["text"])
    description = str(skill["metadata"].get("description", ""))
    body = str(skill["text"]).split("---\n", 2)[-1].lstrip()
    return f"---\ndescription: {json.dumps(description, ensure_ascii=False)}\nalwaysApply: false\n---\n\n{body}"


def plan_install(client_ids: Iterable[str], *, scope: str = "project", project_path: str | Path = ".", home: str | Path | None = None, skills_only: bool = False, mcp_only: bool = False, server_name: str = "codeslicer") -> dict[str, Any]:
    if scope not in {"project", "user"} or (skills_only and mcp_only):
        raise ValueError("scope must be project/user and skills-only cannot be combined with mcp-only")
    project = Path(project_path).expanduser().resolve(); user_home = _home(home)
    assets = bundled_skills(); selected = [resolve_client(value) for value in client_ids]
    unsupported = [item.display_name for item in selected if item.support == "unsupported"]
    if unsupported: raise ValueError(f"unsupported AI client: {', '.join(unsupported)}")
    writes: list[dict[str, Any]] = []
    warnings: list[str] = []
    for adapter in selected:
        if not mcp_only:
            effective_scope, warning = _skill_scope(adapter, scope)
            if warning:
                warnings.append(warning)
            if effective_scope:
                for skill in assets.values():
                    writes.append({"kind": "skill", "client": adapter.id, "path": str(_skill_destination(adapter, project, effective_scope, user_home, skill["name"])), "source_hash": skill["source_hash"]})
        if not skills_only:
            config = None
            if adapter.id == "kodik":
                config = next((path for path in _known_kodik_mcp_paths(user_home) if path.is_file()), None)
            elif scope == "project" and adapter.project_mcp: config = project / adapter.project_mcp
            elif scope == "user" and adapter.user_mcp: config = user_home / adapter.user_mcp
            if config: writes.append({"kind": "mcp", "client": adapter.id, "path": str(config), "key": adapter.mcp_key, "server_name": server_name})
    if any(item.id == "kodik" and not any(write["kind"] == "mcp" and write["client"] == "kodik" for write in writes) for item in selected):
        warnings.append("Kodik MCP is user-level only; use Kodik UI to create mcp.json first if it is not found.")
    return {"project": str(project), "scope": scope, "writes": writes, "launcher": mcp_launcher(), "warnings": warnings}


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file(): return {"schema_version": STATE_VERSION, "clients": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("clients", {}), dict): raise ValueError(f"invalid installer state: {path}")
    return value


def _jsonc_without_comments(text: str) -> str:
    """Parse validation only; writing JSONC is done by a targeted patch below."""
    out: list[str] = []; index = 0; quote = False
    while index < len(text):
        char = text[index]; following = text[index + 1] if index + 1 < len(text) else ""
        if char == '"' and (index == 0 or text[index - 1] != "\\"): quote = not quote
        if not quote and char == "/" and following == "/":
            index = text.find("\n", index); index = len(text) if index < 0 else index; continue
        if not quote and char == "/" and following == "*":
            end = text.find("*/", index + 2)
            if end < 0: raise ValueError("unterminated JSONC comment")
            index = end + 2; continue
        out.append(char); index += 1
    return re.sub(r",\s*([}\]])", r"\1", "".join(out))


def _balanced_close(text: str, opening: int) -> int:
    depth = 0; quote = False; index = opening
    while index < len(text):
        char = text[index]
        if char == '"' and (index == 0 or text[index - 1] != "\\"): quote = not quote
        elif not quote and char == "{": depth += 1
        elif not quote and char == "}":
            depth -= 1
            if depth == 0: return index
        index += 1
    raise ValueError("unbalanced JSONC object")


def _server_entry(path: Path, key: str, server_name: str) -> Any:
    """Return one entry after validating a JSON or JSONC document."""
    if not path.is_file():
        return None
    try:
        document = json.loads(_jsonc_without_comments(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed JSONC config {path}: {exc.msg}") from exc
    servers = document.get(key, {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path} field {key!r} is not an object")
    return servers.get(server_name)


def _backup_once(path: Path, backups: list[dict[str, str]]) -> None:
    """Make one recoverable side-by-side copy before touching a user file."""
    if not path.is_file() or any(item["path"] == str(path) for item in backups):
        return
    backup = path.with_name(f".{path.name}.codeslicer-backup")
    if not backup.exists():
        _atomic_write(backup, path.read_text(encoding="utf-8"))
    backups.append({"path": str(path), "backup_path": str(backup), "sha256": _sha256(path)})


def _skip_jsonc(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1; continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1; continue
        if text.startswith("/*", index):
            close = text.find("*/", index + 2)
            if close < 0: raise ValueError("unterminated JSONC comment")
            index = close + 2; continue
        break
    return index


def _json_value_end(text: str, index: int) -> int:
    index = _skip_jsonc(text, index)
    if index >= len(text): raise ValueError("missing JSONC value")
    if text[index] in "{[":
        opening, closing = text[index], "}" if text[index] == "{" else "]"
        depth, quote = 0, False
        while index < len(text):
            char = text[index]
            if quote:
                if char == "\\": index += 2; continue
                if char == '"': quote = False
            elif char == '"': quote = True
            elif text.startswith("//", index):
                newline = text.find("\n", index + 2); index = len(text) if newline < 0 else newline; continue
            elif text.startswith("/*", index):
                close_at = text.find("*/", index + 2)
                if close_at < 0: raise ValueError("unterminated JSONC comment")
                index = close_at + 2; continue
            elif char == opening: depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0: return index + 1
            index += 1
        raise ValueError("unbalanced JSONC value")
    if text[index] == '"':
        decoder = json.JSONDecoder()
        _value, end = decoder.raw_decode(text[index:])
        return index + end
    end = index
    while end < len(text) and text[end] not in ",}\n\r": end += 1
    return end


def _jsonc_property_span(text: str, object_opening: int, name: str) -> tuple[int, int] | None:
    """Locate one direct object property without normalising comments/formatting."""
    index = _skip_jsonc(text, object_opening + 1)
    while index < len(text) and text[index] != "}":
        start = index
        if text[index] != '"': raise ValueError("malformed JSONC property name")
        property_name, after_name = json.JSONDecoder().raw_decode(text[index:])
        index = _skip_jsonc(text, index + after_name)
        if index >= len(text) or text[index] != ":": raise ValueError("malformed JSONC property")
        end = _json_value_end(text, index + 1)
        if property_name == name:
            after = _skip_jsonc(text, end)
            if after < len(text) and text[after] == ",":
                return start, after + 1
            # Last property: consume the comma that belongs to the previous one.
            before = start - 1
            while before > object_opening and text[before].isspace(): before -= 1
            return (before, end) if text[before] == "," else (start, end)
        index = _skip_jsonc(text, end)
        if index < len(text) and text[index] == ",": index = _skip_jsonc(text, index + 1)
        elif index < len(text) and text[index] != "}": raise ValueError("malformed JSONC object")
    return None


def _patch_jsonc_server(path: Path, key: str, server_name: str, entry: dict[str, Any], *, force: bool) -> tuple[str, str | None]:
    text = path.read_text(encoding="utf-8") if path.is_file() else f'{{\n  {json.dumps(key)}: {{}}\n}}\n'
    try: document = json.loads(_jsonc_without_comments(text))
    except json.JSONDecodeError as exc: raise ValueError(f"malformed JSONC config {path}: {exc.msg}") from exc
    if not isinstance(document, dict): raise ValueError(f"JSONC config {path} root must be an object")
    servers = document.get(key, {})
    if not isinstance(servers, dict): raise ValueError(f"{path} field {key!r} is not an object")
    existing = servers.get(server_name)
    if existing == entry: return "already_installed", None
    if existing is not None and not force: return "conflict", "Existing unmanaged MCP server differs; rerun with --force."
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{', text)
    if not match:
        # Minimal Kilo/Gemini settings often have other preferences but omit
        # mcpServers entirely.  Add only the missing direct root property and
        # preserve the user's formatting/comments everywhere else.
        opening = _skip_jsonc(text, 0)
        if opening >= len(text) or text[opening] != "{": raise ValueError(f"JSONC config {path} root must be an object")
        closing = _balanced_close(text, opening)
        separator = "," if document else ""
        addition = f'{separator}\n  {json.dumps(key)}: {{\n    {json.dumps(server_name)}: {json.dumps(entry, ensure_ascii=False)}\n  }}\n'
        _atomic_write(path, text[:closing] + addition + text[closing:])
        return "installed", None
    opening = text.find("{", match.start()); closing = _balanced_close(text, opening)
    body = text[opening + 1:closing]; separator = "" if not body.strip() else ","
    insertion = f'{separator}\n    {json.dumps(server_name)}: {json.dumps(entry, ensure_ascii=False)}\n  '
    _atomic_write(path, text[:closing] + insertion + text[closing:])
    return "updated" if existing is not None else "installed", None


def _remove_jsonc_server(path: Path, key: str, server_name: str) -> bool:
    """Remove exactly one named entry while preserving the rest of a JSONC file."""
    if not path.is_file(): return False
    text = path.read_text(encoding="utf-8")
    _server_entry(path, key, server_name)  # validates before changing anything
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{', text)
    if not match: raise ValueError(f"JSONC config {path} has no writable {key!r} object")
    opening = text.find("{", match.start())
    span = _jsonc_property_span(text, opening, server_name)
    if span is None: return False
    _atomic_write(path, text[:span[0]] + text[span[1]:])
    # A second validation makes an accidental syntax regression fail closed.
    _server_entry(path, key, server_name)
    return True


def _toml_section_span(text: str, server_name: str) -> tuple[int, int] | None:
    escaped = re.escape(server_name)
    match = re.search(rf'^\[mcp_servers\.(?:{escaped}|"{escaped}")\]\s*$', text, re.MULTILINE)
    if not match: return None
    next_header = re.search(r"^\[", text[match.end():], re.MULTILINE)
    return match.start(), match.end() + (next_header.start() if next_header else len(text) - match.end())


def _toml_entry(path: Path, server_name: str) -> dict[str, Any] | None:
    if not path.is_file(): return None
    text = path.read_text(encoding="utf-8"); span = _toml_section_span(text, server_name)
    if span is None: return None
    section = text[span[0]:span[1]]
    command = re.search(r'^command\s*=\s*("(?:[^"\\]|\\.)*")\s*$', section, re.MULTILINE)
    args = re.search(r'^args\s*=\s*(\[[^\n]*\])\s*$', section, re.MULTILINE)
    if not command or not args: return {"unparseable": True}
    try: return {"command": json.loads(command.group(1)), "args": json.loads(args.group(1))}
    except json.JSONDecodeError: return {"unparseable": True}


def _patch_toml_server(path: Path, server_name: str, entry: dict[str, Any], *, force: bool) -> tuple[str, str | None]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    existing = _toml_entry(path, server_name)
    if existing == entry: return "already_installed", None
    if existing is not None and not force: return "conflict", "Existing unmanaged MCP server differs; rerun with --force."
    rendered = f'[mcp_servers.{server_name}]\ncommand = {json.dumps(entry["command"])}\nargs = {json.dumps(entry["args"])}\n'
    span = _toml_section_span(text, server_name)
    if span is None:
        separator = "" if not text or text.endswith("\n\n") else "\n"
        _atomic_write(path, text + separator + rendered)
        return "installed", None
    _atomic_write(path, text[:span[0]] + rendered + text[span[1]:])
    return "updated", None


def _remove_toml_server(path: Path, server_name: str) -> bool:
    if not path.is_file(): return False
    text = path.read_text(encoding="utf-8"); span = _toml_section_span(text, server_name)
    if span is None: return False
    _atomic_write(path, text[:span[0]] + text[span[1]:])
    return True


def _mcp_entry(adapter: ClientAdapter, path: Path, server_name: str) -> Any:
    return _toml_entry(path, server_name) if adapter.mcp_format == "toml" else _server_entry(path, adapter.mcp_key, server_name)


def _patch_mcp(adapter: ClientAdapter, path: Path, server_name: str, entry: dict[str, Any], *, force: bool) -> tuple[str, str | None]:
    return _patch_toml_server(path, server_name, entry, force=force) if adapter.mcp_format == "toml" else _patch_jsonc_server(path, adapter.mcp_key, server_name, entry, force=force)


def _remove_mcp(adapter: ClientAdapter, path: Path, server_name: str) -> bool:
    return _remove_toml_server(path, server_name) if adapter.mcp_format == "toml" else _remove_jsonc_server(path, adapter.mcp_key, server_name)


def install(client_ids: Iterable[str], *, scope: str = "project", project_path: str | Path = ".", home: str | Path | None = None, skills_only: bool = False, mcp_only: bool = False, link: bool = False, force: bool = False, dry_run: bool = False, server_name: str = "codeslicer", backup: bool = True, progress_callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Install only managed files and a single named MCP entry, transactionally enough for local files."""
    plan = plan_install(client_ids, scope=scope, project_path=project_path, home=home, skills_only=skills_only, mcp_only=mcp_only, server_name=server_name)
    project = Path(plan["project"]); user_home = _home(home); assets = bundled_skills(); state_file = _state_path(project, scope, user_home)
    if dry_run: return {"command": "agent.install", "status": "ok", "changed": False, "result": plan, "warnings": plan["warnings"], "errors": []}
    state = _read_state(state_file); state.update({"schema_version": STATE_VERSION, "installer_version": "0.5.0", "scope": scope, "project_path": str(project), "installed_at": _now()})
    changed = False; warnings = list(plan["warnings"]); errors: list[str] = []; backups: list[dict[str, str]] = []
    selected = [resolve_client(value) for value in client_ids]
    skill_destinations = {
        adapter.id: [Path(write["path"]) for write in plan["writes"] if write["kind"] == "skill" and write["client"] == adapter.id]
        for adapter in selected
    }
    total = (sum(len(destinations) for destinations in skill_destinations.values()) if not mcp_only else 0) + (len(selected) if not skills_only else 0) + 1
    completed = 0

    def report(phase: str, message: str) -> None:
        if progress_callback:
            progress_callback({"phase": phase, "completed": completed, "total": total, "message": message})

    report("preparing", f"Preparing {total} local installation actions")
    for adapter in selected:
        record = state.setdefault("clients", {}).setdefault(adapter.id, {"skills": []})
        if not mcp_only:
            skills = []
            for asset, destination in zip(assets.values(), skill_destinations[adapter.id]):
                report("skills", f"{adapter.display_name}: {asset['name']}")
                rendered = _render_skill(adapter, asset)
                if destination.exists():
                    current = destination.read_text(encoding="utf-8")
                    if current == rendered:
                        skills.append({"name": asset["name"], "source_hash": asset["source_hash"], "installed_path": str(destination), "installed_hash": _sha256(destination), "ownership": "managed-copy"})
                        completed += 1
                        continue
                    if not force:
                        errors.append(f"unmanaged or modified skill exists: {destination}"); completed += 1; continue
                    if backup: _backup_once(destination, backups)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if link:
                    # Assets inside a wheel have no stable filesystem path; link is safe only when resources expose one.
                    warnings.append(f"--link fell back to copy for packaged asset {asset['name']}")
                _atomic_write(destination, rendered); changed = True
                skills.append({"name": asset["name"], "source_hash": asset["source_hash"], "installed_path": str(destination), "installed_hash": _sha256(destination), "ownership": "managed-copy"})
                completed += 1
            record["skills"] = skills
        if not skills_only:
            report("mcp", f"{adapter.display_name}: MCP registration")
            config = next((Path(item["path"]) for item in plan["writes"] if item["kind"] == "mcp" and item["client"] == adapter.id), None)
            if config is None:
                if adapter.id == "kodik": warnings.append("Kodik MCP not registered: create/open its global mcp.json through Kodik UI, then run repair.")
                completed += 1
                continue
            entry = mcp_launcher()
            try:
                if backup and config.is_file() and _mcp_entry(adapter, config, server_name) != entry:
                    _backup_once(config, backups)
                status, warning = _patch_mcp(adapter, config, server_name, entry, force=force)
                if warning: warnings.append(warning)
                elif status != "already_installed": changed = True
                record["mcp"] = {"server_name": server_name, "config_path": str(config), "launcher": entry, "entry_hash": hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()}
            except (OSError, ValueError) as exc: errors.append(str(exc))
            completed += 1
    state["backups"] = backups
    report("saving", "Saving managed installation state")
    _atomic_write(state_file, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    completed += 1
    report("complete", "Local setup is ready")
    return {"command": "agent.install", "status": "partial" if errors else ("ok" if changed else "already_installed"), "changed": changed, "result": {"state_path": str(state_file), "plan": plan, "backups": backups}, "warnings": warnings, "errors": errors}


def installation_status(*, scope: str = "project", project_path: str | Path = ".", home: str | Path | None = None) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve(); user_home = _home(home); state_file = _state_path(project, scope, user_home)
    state = _read_state(state_file); clients: dict[str, Any] = {}
    for client_id, record in state.get("clients", {}).items():
        skills = []
        for item in record.get("skills", []):
            path = Path(item["installed_path"]); current = _sha256(path) if path.is_file() else None
            skills.append({**item, "exists": path.is_file(), "current_hash": current, "modified": bool(current and current != item.get("installed_hash"))})
        mcp = record.get("mcp")
        mcp_status = None
        if isinstance(mcp, dict):
            try:
                current = _mcp_entry(resolve_client(client_id), Path(mcp["config_path"]), mcp["server_name"])
                current_hash = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest() if current is not None else None
                mcp_status = {**mcp, "exists": Path(mcp["config_path"]).is_file(), "registered": current is not None, "modified": bool(current_hash and current_hash != mcp.get("entry_hash"))}
            except (OSError, ValueError) as exc:
                mcp_status = {**mcp, "exists": Path(mcp["config_path"]).is_file(), "registered": False, "error": str(exc)}
        clients[client_id] = {"skills": skills, "mcp": mcp_status}
    return {"command": "agent.status", "status": "ok", "changed": False, "result": {"state_path": str(state_file), "exists": state_file.is_file(), "clients": clients, "launcher": mcp_launcher()}, "warnings": [], "errors": []}


def _readline_with_timeout(stream: Any, timeout: float) -> bytes:
    result: list[bytes] = []
    thread = threading.Thread(target=lambda: result.append(stream.readline()), daemon=True); thread.start(); thread.join(timeout)
    if thread.is_alive(): raise TimeoutError("MCP response timed out")
    if not result or not result[0]: raise RuntimeError("MCP process closed stdout")
    return result[0]


def doctor(*, timeout_seconds: float = 10) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        assets = bundled_skills(); checks.append({"name": "bundled_skills", "status": "ok", "skills": sorted(assets)})
    except (OSError, ValueError) as exc:
        return {"command": "agent.doctor", "status": "error", "changed": False, "result": {"checks": checks}, "warnings": [], "errors": [str(exc)]}
    launcher = mcp_launcher(); command = [launcher["command"], *launcher["args"]]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    try:
        assert process.stdin and process.stdout
        for request in ({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}}}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}):
            process.stdin.write((json.dumps(request) + "\n").encode("utf-8")); process.stdin.flush()
            response = json.loads(_readline_with_timeout(process.stdout, timeout_seconds).decode("utf-8"))
            if request["id"] == 1:
                initialized = response.get("result", {})
                if initialized.get("protocolVersion") != "2024-11-05" or not initialized.get("serverInfo"): raise ValueError("MCP initialize contract is invalid")
            else:
                tools = {item.get("name") for item in response.get("result", {}).get("tools", []) if isinstance(item, dict)}
                missing = {"scan_plan", "project_status", "review", "inspect"} - tools
                if missing: raise ValueError(f"MCP tools/list misses: {', '.join(sorted(missing))}")
        checks.append({"name": "mcp_handshake", "status": "ok", "launcher": launcher})
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError) as exc:
        checks.append({"name": "mcp_handshake", "status": "error", "launcher": launcher, "message": str(exc)})
    finally:
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
    errors = [str(item.get("message")) for item in checks if item["status"] == "error"]
    return {"command": "agent.doctor", "status": "error" if errors else "ok", "changed": False, "result": {"checks": checks}, "warnings": [], "errors": errors}


def _recoverable_clients(project: Path, scope: str, home: Path) -> list[str]:
    """Identify only exact managed copies when a state file was lost."""
    assets = bundled_skills(); launcher = mcp_launcher(); recovered: list[str] = []; claimed_skill_paths: set[Path] = set()
    for adapter in CLIENTS:
        if adapter.support == "unsupported": continue
        try:
            effective_scope, _warning = _skill_scope(adapter, scope)
            destinations = [_skill_destination(adapter, project, effective_scope, home, asset["name"]) for asset in assets.values()] if effective_scope else []
            skills_match = bool(destinations) and not any(path in claimed_skill_paths for path in destinations) and all(
                destination.is_file() and destination.read_text(encoding="utf-8") == _render_skill(adapter, asset)
                for destination, asset in zip(destinations, assets.values())
            )
            config = next((item for item in _known_kodik_mcp_paths(home) if item.is_file()), None) if adapter.id == "kodik" else (project / adapter.project_mcp if scope == "project" and adapter.project_mcp else home / adapter.user_mcp if scope == "user" and adapter.user_mcp else None)
            mcp_match = bool(config and _mcp_entry(adapter, config, "codeslicer") == launcher)
            if skills_match or mcp_match:
                recovered.append(adapter.id)
                if skills_match: claimed_skill_paths.update(destinations)
        except (OSError, ValueError):
            continue
    return recovered


def repair(*, scope: str = "project", project_path: str | Path = ".", home: str | Path | None = None, force: bool = False, dry_run: bool = False, backup: bool = True) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve(); user_home = _home(home); state = _read_state(_state_path(project, scope, user_home))
    clients = list(state.get("clients", {}))
    recovered = False
    if not clients:
        clients = _recoverable_clients(project, scope, user_home); recovered = bool(clients)
    if not clients: return {"command": "agent.repair", "status": "error", "changed": False, "result": {}, "warnings": [], "errors": ["no installation state found and no exact managed installation could be recovered"]}
    result = install(clients, scope=scope, project_path=project, home=user_home, force=force, dry_run=dry_run, backup=backup)
    result["command"] = "agent.repair"
    if recovered: result["warnings"].append("installation state was reconstructed from exact managed files")
    return result


def uninstall(*, scope: str = "project", project_path: str | Path = ".", home: str | Path | None = None, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve(); user_home = _home(home); state_file = _state_path(project, scope, user_home); state = _read_state(state_file)
    if not state.get("clients"):
        return {"command": "agent.uninstall", "status": "error", "changed": False, "result": {}, "warnings": [], "errors": ["no installation state found"]}
    removed: list[str] = []; warnings: list[str] = []; errors: list[str] = []; retained: set[str] = set(); preserved_skills: set[str] = set()
    # First establish whether each client can be fully uninstalled.  This is
    # what makes a shared .agents/skills copy safe to remove exactly once.
    for client_id, record in state["clients"].items():
        for skill in record.get("skills", []):
            path = Path(skill["installed_path"])
            if path.is_file() and _sha256(path) != skill.get("installed_hash") and not force:
                warnings.append(f"preserved user-modified skill: {path}"); preserved_skills.add(client_id)
        mcp = record.get("mcp")
        if isinstance(mcp, dict):
            try:
                actual = _mcp_entry(resolve_client(client_id), Path(mcp["config_path"]), mcp["server_name"])
                actual_hash = hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest() if actual is not None else None
                if actual is not None and actual_hash != mcp.get("entry_hash") and not force:
                    warnings.append(f"preserved user-modified MCP entry: {mcp['config_path']}"); retained.add(client_id)
            except (OSError, ValueError) as exc:
                errors.append(str(exc)); retained.add(client_id)
    for client_id, record in list(state["clients"].items()):
        if client_id not in preserved_skills:
            for skill in record.get("skills", []):
                path = Path(skill["installed_path"])
                # Keep a shared file until no still-managed adapter needs it.
                other_owners = [other for other, other_record in state["clients"].items() if other != client_id and any(Path(item["installed_path"]) == path for item in other_record.get("skills", []))]
                if other_owners: continue
                if path.is_file():
                    if not dry_run: path.unlink()
                    removed.append(str(path))
        mcp = record.get("mcp")
        if isinstance(mcp, dict):
            try:
                config = Path(mcp["config_path"])
                if dry_run:
                    if _mcp_entry(resolve_client(client_id), config, mcp["server_name"]) is not None:
                        warnings.append(f"dry-run: would remove MCP entry {config}::{mcp['server_name']}")
                elif _remove_mcp(resolve_client(client_id), config, mcp["server_name"]):
                    removed.append(f"{config}::{mcp['server_name']}")
            except (OSError, ValueError) as exc:
                errors.append(str(exc)); retained.add(client_id); continue
        if client_id not in retained and client_id not in preserved_skills and not dry_run: state["clients"].pop(client_id, None)
    if not dry_run:
        if state.get("clients"): _atomic_write(state_file, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        elif state_file.exists(): state_file.unlink()
    return {"command": "agent.uninstall", "status": "error" if errors else ("partial" if warnings else "ok"), "changed": bool(removed), "result": {"removed": removed, "state_path": str(state_file)}, "warnings": warnings, "errors": errors}
