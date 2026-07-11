from __future__ import annotations

import re
from urllib.parse import urlsplit

from .models import CanonicalRoute

_PARAM_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def canonical_route_key(method: str | None, path: str) -> str:
    normalized_method = method.upper() if method else "*"
    return f"{normalized_method} {path}"


class RouteNormalizer:
    def normalize(self, route: str, method: str | None = None, source: str | None = None) -> CanonicalRoute:
        original = route
        reasons: list[str] = []
        param_names: list[str] = []
        confidence = 0.30
        method_norm = method.upper() if method else None
        if method and method_norm != method:
            reasons.append("method normalized to uppercase")

        text = route.strip()
        text = self._strip_wrapping_quotes_or_backticks(text)
        text = self._remove_query_string(text)

        if "+" in text:
            confidence = max(confidence, 0.65)
            reasons.append("route expression appears concatenated")
            text, names = self._normalize_concatenation(text)
            param_names.extend(names)
        else:
            if "${" in text:
                confidence = max(confidence, 0.85)
                reasons.append("template parameter syntax detected")
            elif any(ch in text for ch in ["{", ":", "<"]):
                confidence = max(confidence, 0.95)
                reasons.append("literal path with parameter syntax detected")
            elif text.startswith("/"):
                confidence = max(confidence, 0.95)
                reasons.append("clear literal path detected")

        text, names = self._replace_params(text)
        param_names.extend(names)
        text = self._cleanup_path(text)

        if not text.startswith("/"):
            if text:
                text = "/" + text
            reasons.append("path did not start with slash")

        if text == "/":
            confidence = min(confidence, 0.80)
        if not original.strip():
            confidence = 0.30
            reasons.append("empty route string")

        seen: set[str] = set()
        ordered_names = []
        for name in param_names:
            clean = self._clean_param_name(name)
            if clean and clean not in seen:
                seen.add(clean)
                ordered_names.append(clean)

        return CanonicalRoute(
            method=method_norm,
            original=original,
            canonical_path=text,
            param_names=ordered_names,
            confidence=round(confidence, 2),
            reasons=reasons or ["normalized route path"],
            source=source,
        )

    def equivalent(self, a: str, b: str, method_a: str | None = None, method_b: str | None = None) -> bool:
        ar = self.normalize(a, method_a)
        br = self.normalize(b, method_b)
        if ar.canonical_path != br.canonical_path:
            return False
        if ar.method is None or br.method is None:
            return True
        return ar.method == br.method

    def equivalent_strict(self, a: str, b: str, method_a: str | None, method_b: str | None) -> bool:
        ar = self.normalize(a, method_a)
        br = self.normalize(b, method_b)
        return canonical_route_key(ar.method, ar.canonical_path) == canonical_route_key(br.method, br.canonical_path)

    def _strip_wrapping_quotes_or_backticks(self, text: str) -> str:
        text = text.strip()
        while len(text) >= 2 and ((text[0] == text[-1] and text[0] in {'"', "'", "`"})):
            text = text[1:-1].strip()
        return text

    def _remove_query_string(self, text: str) -> str:
        # Avoid urlsplit for JS expressions like "/x/" + id. For normal strings,
        # query starts at the first ?.
        if "?" in text:
            return text.split("?", 1)[0]
        return text

    def _normalize_concatenation(self, text: str) -> tuple[str, list[str]]:
        parts = [p.strip() for p in text.split("+")]
        normalized = ""
        names: list[str] = []
        for part in parts:
            stripped = self._strip_wrapping_quotes_or_backticks(part)
            if not part:
                continue
            if part[0:1] in {'"', "'", "`"} and part[-1:] == part[0:1]:
                normalized += stripped
                continue
            encode_match = re.match(r"encodeURIComponent\(([^)]+)\)", part)
            if encode_match:
                name = encode_match.group(1).strip()
                names.append(name)
                normalized += "{param}"
                continue
            if _PARAM_NAME_RE.fullmatch(part):
                names.append(part)
                normalized += "{param}"
                continue
            # Unknown expression still likely parameter-like in route concatenation.
            expr_name = self._clean_param_name(part) or "expr"
            names.append(expr_name)
            normalized += "{param}"
        return normalized, names

    def _replace_params(self, text: str) -> tuple[str, list[str]]:
        names: list[str] = []

        def repl_template(m: re.Match[str]) -> str:
            names.append(m.group(1).strip())
            return "{param}"

        # Template parameters must be processed before brace parameters so
        # `${id}` preserves `id`, not the intermediate `{param}` token.
        text = re.sub(r"\$\{\s*([^}]+?)\s*\}", repl_template, text)

        def repl_brace(m: re.Match[str]) -> str:
            name = m.group(1).strip()
            # Do not expose the internal canonical marker as an original name.
            if name != "param":
                names.append(name)
            return "{param}"

        text = re.sub(r"\{\s*([^}/]+?)\s*\}", repl_brace, text)

        def repl_angle(m: re.Match[str]) -> str:
            names.append(m.group(1).strip())
            return "/{param}"

        text = re.sub(r"/<\s*([^>/]+?)\s*>", repl_angle, text)

        def repl_colon(m: re.Match[str]) -> str:
            names.append(m.group(1).strip())
            return "/{param}"

        text = re.sub(r"/:([A-Za-z_][A-Za-z0-9_]*)", repl_colon, text)
        return text, names

    def _cleanup_path(self, path: str) -> str:
        path = path.replace("\\", "/")
        path = re.sub(r"/{2,}", "/", path)
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        return path or "/"

    def _clean_param_name(self, name: str) -> str:
        name = name.strip().strip("{}$()[] ")
        # Convert common JS identifiers into snake-ish lower form for machine readability,
        # while preserving original semantics enough for debugging.
        name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
        if not name:
            return ""
        return name
