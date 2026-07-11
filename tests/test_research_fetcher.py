import pytest
from impact_engine.research.fetcher import WebFetcher


class MockResponse:
    def __init__(self, status_code, content, headers):
        self.status_code = status_code
        self.content = content
        self.headers = headers

    def iter_content(self, chunk_size=8192):
        yield self.content


def test_fetch_only_https():
    fetcher = WebFetcher()
    res = fetcher.fetch_url("http://example.com")
    assert res.error == "Only HTTPS URLs are allowed"


def test_fetch_html_strips_tags(monkeypatch):
    def mock_get(*args, **kwargs):
        return MockResponse(
            status_code=200,
            content=b"<html><head><title>Test</title></head><body><h1>Hello World</h1><script>ignore me</script></body></html>",
            headers={"content-type": "text/html"}
        )
    monkeypatch.setattr("requests.get", mock_get)

    fetcher = WebFetcher()
    res = fetcher.fetch_url("https://example.com")
    assert res.status_code == 200
    assert "Hello World" in res.text_excerpt
    assert "ignore me" not in res.text_excerpt


def test_fetch_many_respects_max_pages(monkeypatch):
    fetched_urls = []
    
    def mock_get(url, *args, **kwargs):
        fetched_urls.append(url)
        return MockResponse(
            status_code=200,
            content=b"content",
            headers={"content-type": "text/plain"}
        )
    monkeypatch.setattr("requests.get", mock_get)
    
    fetcher = WebFetcher()
    urls = [
        "https://url1.com",
        "https://url2.com",
        "https://url3.com",
        "https://url4.com"
    ]
    
    # max_pages = 2
    results = fetcher.fetch_many(urls, max_pages=2)
    assert len(results) == 2
    assert len(fetched_urls) == 2
    assert fetched_urls == ["https://url1.com", "https://url2.com"]
