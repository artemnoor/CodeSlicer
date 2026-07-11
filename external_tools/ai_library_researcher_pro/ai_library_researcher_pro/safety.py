from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse


class SafetyError(RuntimeError):
    """Base class for blocked unsafe operations."""


class NetworkNotAllowed(SafetyError):
    pass


class UnsafeUrlBlocked(SafetyError):
    pass


class ContentTooLarge(SafetyError):
    pass


class UnsupportedContentType(SafetyError):
    pass


@dataclass(frozen=True)
class SafetyLimits:
    max_url_count: int = 12
    max_page_size_bytes: int = 250_000
    max_total_bytes: int = 1_000_000
    timeout_seconds: float = 8.0


class SafetyPolicy:
    """Network/content guardrails.

    The policy never executes downloaded code and does not allow recursive crawling.
    """

    blocked_schemes = {"file", "ftp", "sftp", "ssh"}
    allowed_network_schemes = {"http", "https"}
    allowed_local_schemes = {"local"}

    def __init__(self, allow_network: bool, limits: Optional[SafetyLimits] = None) -> None:
        self.allow_network = allow_network
        self.limits = limits or SafetyLimits()

    def validate_url_count(self, urls: Iterable[str]) -> None:
        count = len(list(urls))
        if count > self.limits.max_url_count:
            raise UnsafeUrlBlocked(f"too many URLs requested: {count} > {self.limits.max_url_count}")

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme in self.blocked_schemes:
            raise UnsafeUrlBlocked(f"blocked URL scheme: {scheme}")
        if scheme in self.allowed_local_schemes:
            return
        if scheme not in self.allowed_network_schemes:
            raise UnsafeUrlBlocked(f"unsupported URL scheme: {scheme or '<empty>'}")
        if not self.allow_network:
            raise NetworkNotAllowed("network access requires explicit allow_network=True / --allow-network")
        host = parsed.hostname or ""
        if self._is_private_or_local_host(host):
            raise UnsafeUrlBlocked(f"blocked private/local host: {host}")

    def validate_local_path(self, local_path: Path, project_root: Path) -> Path:
        root = project_root.resolve()
        candidate = local_path if local_path.is_absolute() else root / local_path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise UnsafeUrlBlocked(f"local path escapes project root: {local_path}") from exc
        if not resolved.is_file():
            raise UnsafeUrlBlocked(f"local fixture is not a file: {local_path}")
        return resolved

    @staticmethod
    def _is_private_or_local_host(host: str) -> bool:
        normalized = host.strip().lower().rstrip(".")
        if not normalized:
            return True
        if normalized in {"localhost", "0", "0.0.0.0"}:
            return True
        if normalized.endswith(".local"):
            return True
        try:
            ip = ipaddress.ip_address(normalized)
            return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
        except ValueError:
            pass
        # Avoid DNS lookups for arbitrary hosts in validation. Block obvious local names.
        if normalized.startswith(("localhost", "127.", "10.", "192.168.", "172.16.")):
            return True
        return False


def content_type_allowed(content_type: str) -> bool:
    lowered = (content_type or "").split(";")[0].strip().lower()
    return lowered in {
        "text/html",
        "text/markdown",
        "text/plain",
        "application/json",
        "application/xhtml+xml",
        "application/xml",
    }
