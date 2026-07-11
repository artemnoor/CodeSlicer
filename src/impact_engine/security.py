"""Local input and resource safety checks."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


def validate_project_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"Project path does not exist: {candidate}")
    if not candidate.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {candidate}")
    return candidate


def validate_research_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Only HTTPS URLs are allowed")
    return url


def bounded_json_loads(text: str, max_bytes: int = 10_000_000) -> dict:
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError(f"JSON payload exceeds {max_bytes} bytes")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("JSON payload must be an object")
    return value
