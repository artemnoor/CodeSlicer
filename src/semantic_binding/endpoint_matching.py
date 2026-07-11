from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .path_templates import normalize_path


_PLACEHOLDER_RE = re.compile(r"^(\{[^/]+\}|\$\{[^/]+\}|:[^/]+)$")


@dataclass(frozen=True)
class EndpointMatch:
    frontend: str
    backend: str
    confidence: float
    reason: str


def split_segments(path: str) -> List[str]:
    path = normalize_path(path)
    if path == "/":
        return []
    return [segment for segment in path.strip("/").split("/") if segment]


def is_placeholder(segment: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(segment))


def match_endpoint(frontend: str, backend: str) -> EndpointMatch:
    left = split_segments(frontend)
    right = split_segments(backend)
    if normalize_path(frontend) == normalize_path(backend):
        return EndpointMatch(frontend, backend, 1.0, "exact literal path match")
    if len(left) != len(right):
        return EndpointMatch(frontend, backend, 0.0, "different segment counts")
    placeholder_pairs = 0
    literal_matches = 0
    for a, b in zip(left, right):
        if a == b:
            literal_matches += 1
            continue
        if is_placeholder(a) and is_placeholder(b):
            placeholder_pairs += 1
            continue
        if is_placeholder(a) or is_placeholder(b):
            placeholder_pairs += 1
            continue
        return EndpointMatch(frontend, backend, 0.0, f"literal segment mismatch: {a!r} != {b!r}")
    confidence = 0.82 + min(0.13, literal_matches * 0.02) if placeholder_pairs else 1.0
    return EndpointMatch(frontend, backend, min(confidence, 0.95), "template path match" if placeholder_pairs else "exact path match")


def match_endpoints(frontend_paths: List[str], backend_paths: List[str], min_confidence: float = 0.8) -> List[EndpointMatch]:
    matches: List[EndpointMatch] = []
    for frontend in frontend_paths:
        for backend in backend_paths:
            match = match_endpoint(frontend, backend)
            if match.confidence >= min_confidence:
                matches.append(match)
    return sorted(matches, key=lambda m: (m.frontend, m.backend, -m.confidence))
