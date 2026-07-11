"""HTTP route canonicalization utilities."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from .models import CanonicalRoute

_TEMPLATE_PARAM_RE = re.compile(r"\$\{[^}/]+\}")
_BRACE_PARAM_RE = re.compile(r"\{[^}/]+\}")
_ANGLE_PARAM_RE = re.compile(r"<[^>/]+>")
_COLON_PARAM_RE = re.compile(r"(?<=/):[^/?#]+")
_MULTI_SLASH_RE = re.compile(r"/{2,}")


def normalize_query(query: str) -> str:
    """Return a stable representation of a query string.

    Query strings are deliberately separated from route path matching. We sort
    parameters to make diagnostics deterministic, but backend route matching is
    performed on the canonical path only.
    """

    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return ""
    return urlencode(sorted(pairs), doseq=True)


def _strip_scheme_host(raw: str) -> str:
    stripped = raw.strip()
    if not stripped:
        return stripped
    parts = urlsplit(stripped)
    if parts.scheme and parts.netloc:
        path = parts.path or "/"
        if parts.query:
            return f"{path}?{parts.query}"
        return path
    return stripped


def canonicalize_path(raw_path: str | None, *, keep_query: bool = True) -> CanonicalRoute:
    """Canonicalize frontend or backend path templates.

    Supported dynamic parameter syntaxes are normalized to ``{param}``:
    ``{id}``, ``:id``, ``${id}``, and ``<id>``.
    """

    raw = "" if raw_path is None else str(raw_path)
    trimmed = _strip_scheme_host(raw)
    if not trimmed:
        return CanonicalRoute(raw=raw, path="", query="", dynamic_segments=0)

    # Do not call urlsplit here for schemeless paths such as //api//v1: 
    # urllib treats the first segment as a network location. At this point
    # _strip_scheme_host has already removed real absolute URL hosts.
    if "?" in trimmed:
        path, query = trimmed.split("?", 1)
    else:
        path, query = trimmed, ""

    had_trailing_slash = path.endswith("/") and path != "/"
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    path = _MULTI_SLASH_RE.sub("/", path)

    path = _TEMPLATE_PARAM_RE.sub("{param}", path)
    path = _ANGLE_PARAM_RE.sub("{param}", path)
    path = _COLON_PARAM_RE.sub("{param}", path)
    path = _BRACE_PARAM_RE.sub("{param}", path)

    # Stable trailing slash behavior: route keys do not distinguish trailing /
    # except for root.
    if path != "/":
        path = path.rstrip("/")

    dynamic_segments = sum(1 for segment in path.split("/") if segment == "{param}")
    return CanonicalRoute(
        raw=raw,
        path=path,
        query=normalize_query(query) if keep_query else "",
        dynamic_segments=dynamic_segments,
        had_trailing_slash=had_trailing_slash,
    )


def canonicalize_route(method: str, path: str | None) -> tuple[str, CanonicalRoute]:
    """Canonicalize an HTTP method/path pair."""

    return method.upper().strip(), canonicalize_path(path)


def path_suffix_equal(left: str, right: str) -> bool:
    """Return true if two different paths share a route-like suffix.

    This is a false-positive guard signal only. For example,
    /legacy/v1/shop/orders and /api/v1/shop/orders both end in
    /v1/shop/orders or /shop/orders, but their prefixes differ, so the resolver
    may report a suspicious candidate and must not confirm it.
    """

    left_c = canonicalize_path(left).path
    right_c = canonicalize_path(right).path
    if not left_c or not right_c or left_c == right_c:
        return False
    left_segments = [p for p in left_c.split("/") if p]
    right_segments = [p for p in right_c.split("/") if p]
    if not left_segments or not right_segments:
        return False
    common = 0
    for l_seg, r_seg in zip(reversed(left_segments), reversed(right_segments)):
        if l_seg != r_seg:
            break
        common += 1
    # One shared terminal segment is enough to warn about suffix-only route
    # similarity. The caller still caps this at suspicious/0.50.
    return common > 0
