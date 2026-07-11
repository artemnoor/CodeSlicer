from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional

from .models import FetchedPage, ResearchSource
from .safety import (
    ContentTooLarge,
    SafetyLimits,
    SafetyPolicy,
    UnsupportedContentType,
    content_type_allowed,
)


class SafeHTTPFetcher:
    """Bounded, non-recursive fetcher.

    It never executes downloaded content. Remote network access requires an
    explicit allow_network=True policy.
    """

    def __init__(self, policy: SafetyPolicy, user_agent: str = "ai-library-researcher-pro/0.1", rate_limit_seconds: float = 0.05) -> None:
        self.policy = policy
        self.user_agent = user_agent
        self.rate_limit_seconds = rate_limit_seconds
        self._total_bytes = 0

    def fetch_many(self, sources: Iterable[ResearchSource], project_root: str | Path = ".") -> List[FetchedPage]:
        sources = list(sources)
        self.policy.validate_url_count([s.url for s in sources])
        pages: List[FetchedPage] = []
        for source in sources:
            try:
                pages.append(self.fetch_source(source, project_root=project_root))
            except Exception as exc:  # keep workflows resilient; CLI maps direct safety errors where needed
                pages.append(
                    FetchedPage(
                        source_url=source.url,
                        source_type=source.source_type,
                        title=source.title,
                        error=f"{exc.__class__.__name__}: {exc}",
                        bytes_read=0,
                        local_path=source.local_path,
                    )
                )
            time.sleep(self.rate_limit_seconds)
        return pages

    def fetch_source(self, source: ResearchSource, project_root: str | Path = ".") -> FetchedPage:
        if source.local_path or source.url.startswith("local://"):
            return self._fetch_local(source, Path(project_root))
        return self.fetch_url(source.url, source_type=source.source_type, title=source.title, local_path=source.local_path)

    def fetch_url(self, url: str, source_type: str = "remote", title: str = "", local_path: Optional[str] = None) -> FetchedPage:
        self.policy.validate_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.policy.limits.timeout_seconds) as response:
                content_type = response.headers.get("Content-Type", "text/plain")
                if not content_type_allowed(content_type):
                    raise UnsupportedContentType(f"blocked content type: {content_type}")
                data = response.read(self.policy.limits.max_page_size_bytes + 1)
                if len(data) > self.policy.limits.max_page_size_bytes:
                    raise ContentTooLarge(f"page exceeds max_page_size_bytes={self.policy.limits.max_page_size_bytes}")
                self._add_total(len(data))
                text = data.decode(_encoding_from_content_type(content_type), errors="replace")
                return FetchedPage(
                    source_url=url,
                    source_type=source_type,
                    title=title,
                    content_type=content_type,
                    text_excerpt=text,
                    status_code=getattr(response, "status", None),
                    bytes_read=len(data),
                    local_path=local_path,
                )
        except urllib.error.URLError as exc:
            raise RuntimeError(f"fetch failed for {url}: {exc}") from exc

    def _fetch_local(self, source: ResearchSource, project_root: Path) -> FetchedPage:
        local = source.local_path
        if not local:
            marker = "local://project/"
            if not source.url.startswith(marker):
                raise ValueError(f"unsupported local URL: {source.url}")
            local = source.url[len(marker):]
        resolved = self.policy.validate_local_path(Path(local), project_root)
        data = resolved.read_bytes()
        if len(data) > self.policy.limits.max_page_size_bytes:
            raise ContentTooLarge(f"local page exceeds max_page_size_bytes={self.policy.limits.max_page_size_bytes}")
        self._add_total(len(data))
        content_type = _content_type_for_suffix(resolved.suffix)
        return FetchedPage(
            source_url=source.url,
            source_type=source.source_type,
            title=source.title or resolved.name,
            content_type=content_type,
            text_excerpt=data.decode("utf-8", errors="replace"),
            status_code=200,
            bytes_read=len(data),
            local_path=local,
        )

    def _add_total(self, size: int) -> None:
        self._total_bytes += size
        if self._total_bytes > self.policy.limits.max_total_bytes:
            raise ContentTooLarge(f"fetched total exceeds max_total_bytes={self.policy.limits.max_total_bytes}")


def _content_type_for_suffix(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix == ".json":
        return "application/json"
    return "text/plain"


def _encoding_from_content_type(content_type: str) -> str:
    parts = [p.strip() for p in (content_type or "").split(";")]
    for part in parts[1:]:
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip() or "utf-8"
    return "utf-8"
