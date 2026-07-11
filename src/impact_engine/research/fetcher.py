"""Web Fetcher with bandwidth limits and tag stripping. Stage 14."""
from dataclasses import dataclass
from typing import Optional
from html.parser import HTMLParser
import requests
from impact_engine.security import validate_research_url


@dataclass
class FetchResult:
    url: str
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    text_excerpt: Optional[str] = None
    error: Optional[str] = None


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.ignore = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "meta", "link", "noscript"):
            self.ignore = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "meta", "link", "noscript"):
            self.ignore = False

    def handle_data(self, data):
        if not self.ignore:
            text = data.strip()
            if text:
                self.text_parts.append(text)

    def get_text(self) -> str:
        return " ".join(self.text_parts)


class WebFetcher:
    def __init__(self, timeout: int = 10, max_bytes: int = 500_000):
        self.timeout = timeout
        self.max_bytes = max_bytes

    def fetch_url(self, url: str, timeout_seconds: int = 10) -> FetchResult:
        try:
            validate_research_url(url)
        except ValueError as exc:
            return FetchResult(url=url, error=str(exc))
            
        try:
            # Stream response to check size and content type
            response = requests.get(url, timeout=timeout_seconds, stream=True, allow_redirects=False)
            status_code = response.status_code
            content_type = response.headers.get("content-type", "")
            
            # Read chunk by chunk up to max_bytes
            content_bytes = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                if len(content_bytes) + len(chunk) > self.max_bytes:
                    content_bytes.extend(chunk[:self.max_bytes - len(content_bytes)])
                    break
                content_bytes.extend(chunk)
                
            text = content_bytes.decode("utf-8", errors="ignore")
            
            # If HTML, strip tags
            if "html" in content_type.lower():
                try:
                    parser = HTMLTextExtractor()
                    parser.feed(text)
                    excerpt = parser.get_text()
                except Exception:
                    excerpt = text  # Fallback to raw text if parsing fails
            else:
                excerpt = text
                
            # Truncate to a reasonable summary excerpt
            excerpt = excerpt[:10000]
            
            return FetchResult(
                url=url,
                status_code=status_code,
                content_type=content_type,
                text_excerpt=excerpt
            )
            
        except Exception as e:
            return FetchResult(url=url, error=str(e))

    def fetch(self, url: str) -> FetchResult:
        return self.fetch_url(url, timeout_seconds=self.timeout)

    def fetch_many(self, urls: list[str], max_pages: int = 5) -> list[FetchResult]:
        results = []
        for url in urls[:max_pages]:
            results.append(self.fetch_url(url, timeout_seconds=self.timeout))
        return results
