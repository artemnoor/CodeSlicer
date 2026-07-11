from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional

_TEMPLATE_RE = re.compile(r"\$\{[^}]+\}")
_CALL_RE = re.compile(r"^([A-Za-z_$][\w.$]*)\((.*)\)$")


def normalize_endpoint_value(value: Any, path_builder_functions: Iterable[str] = ()) -> Optional[str]:
    builders = {str(item) for item in path_builder_functions}
    if isinstance(value, dict):
        return _normalize_dict_value(value, builders)
    if isinstance(value, list):
        return _normalize_parts(value, builders)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    call_match = _CALL_RE.match(text)
    if call_match and call_match.group(1) in builders:
        args = _split_args(call_match.group(2))
        return _normalize_parts(args, builders)

    if "+" in text:
        parts = _split_concat(text)
        normalized = _normalize_parts(parts, builders)
        if normalized:
            return normalized

    literal = _strip_quotes(text)
    literal = _replace_template_params(literal)
    if literal.startswith("http://") or literal.startswith("https://"):
        # Keep only path-like suffix when possible, otherwise leave absolute URL.
        match = re.match(r"https?://[^/]+(/.*)?$", literal)
        literal = match.group(1) or "/" if match else literal
    if literal.startswith("/"):
        return normalize_path(literal)
    return None


def normalize_path(path: str) -> str:
    if not path:
        return "/"
    path = path.split("?", 1)[0]
    path = _replace_template_params(path)
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _normalize_dict_value(value: dict, builders: set[str]) -> Optional[str]:
    kind = value.get("kind") or value.get("type")
    if kind in {"template", "concat", "path", "path_template"}:
        return _normalize_parts(value.get("parts") or value.get("segments") or value.get("args") or [], builders)
    if kind == "call" or value.get("function") or value.get("builder"):
        function = str(value.get("function") or value.get("builder") or "")
        if builders and function not in builders:
            return None
        return _normalize_parts(value.get("args") or [], builders)
    if "path" in value:
        return normalize_endpoint_value(value.get("path"), builders)
    return None


def _normalize_parts(parts: Iterable[Any], builders: set[str]) -> Optional[str]:
    rendered: List[str] = []
    for index, part in enumerate(parts):
        if isinstance(part, dict):
            if "literal" in part:
                rendered.append(_replace_template_params(str(part["literal"])))
            elif "param" in part or part.get("kind") == "param":
                rendered.append("/{param}" if rendered and not rendered[-1].endswith("/") else "{param}")
            else:
                nested = normalize_endpoint_value(part, builders)
                if nested:
                    rendered.append(nested)
                else:
                    rendered.append("/{param}" if rendered and not rendered[-1].endswith("/") else "{param}")
            continue
        text = str(part).strip()
        if not text:
            continue
        literal = _strip_quotes(text)
        if literal.startswith("/") or "${" in literal:
            rendered.append(_replace_template_params(literal))
        elif index == 0 and (literal.startswith("http://") or literal.startswith("https://")):
            rendered.append(normalize_endpoint_value(literal, builders) or literal)
        else:
            rendered.append("/{param}" if rendered and not rendered[-1].endswith("/") else "{param}")
    if not rendered:
        return None
    joined = "".join(rendered)
    if not joined.startswith("/"):
        return None
    return normalize_path(joined)


def _strip_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'", "`"}:
        return text[1:-1]
    return text


def _replace_template_params(text: str) -> str:
    return _TEMPLATE_RE.sub("{param}", text)


def _split_concat(text: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in {'"', "'", "`"}:
            quote = ch
            current.append(ch)
            continue
        if ch == "+":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _split_args(text: str) -> List[str]:
    args: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    depth = 0
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in {'"', "'", "`"}:
            quote = ch
            current.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth:
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args
