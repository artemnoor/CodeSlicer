from __future__ import annotations

import io
from pathlib import Path

import pytest

from ai_library_researcher_pro.fetcher import SafeHTTPFetcher
from ai_library_researcher_pro.models import ResearchSource
from ai_library_researcher_pro.safety import ContentTooLarge, NetworkNotAllowed, SafetyLimits, SafetyPolicy, UnsafeUrlBlocked


def test_fetcher_blocks_network_when_allow_network_false():
    fetcher = SafeHTTPFetcher(SafetyPolicy(allow_network=False))
    with pytest.raises(NetworkNotAllowed):
        fetcher.fetch_url("https://example.com")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/file", "http://localhost:8000", "http://127.0.0.1:8000", "http://10.0.0.1/"])
def test_fetcher_blocks_unsafe_urls(url: str):
    fetcher = SafeHTTPFetcher(SafetyPolicy(allow_network=True))
    with pytest.raises(UnsafeUrlBlocked):
        fetcher.fetch_url(url)


def test_fetcher_enforces_max_bytes_for_local_files(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "big.md").write_text("x" * 20, encoding="utf-8")
    fetcher = SafeHTTPFetcher(SafetyPolicy(allow_network=False, limits=SafetyLimits(max_page_size_bytes=5)))
    source = ResearchSource(url="local://project/big.md", source_type="local_project_doc", local_path="big.md")
    with pytest.raises(ContentTooLarge):
        fetcher.fetch_source(source, project_root=root)


def test_fetcher_passes_timeout_to_urlopen(monkeypatch):
    called = {}

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size):
            return b"hello"

    def fake_urlopen(request, timeout):
        called["timeout"] = timeout
        return FakeResponse()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    fetcher = SafeHTTPFetcher(SafetyPolicy(allow_network=True, limits=SafetyLimits(timeout_seconds=3.5)))
    page = fetcher.fetch_url("https://example.com/docs")

    assert called["timeout"] == 3.5
    assert page.text_excerpt == "hello"
