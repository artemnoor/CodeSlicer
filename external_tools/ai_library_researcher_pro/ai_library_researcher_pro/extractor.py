from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from typing import Iterable, List, Tuple

from .models import ExtractedExample, FetchedPage


class _StructuredHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: List[str] = []
        self.code_blocks: List[str] = []
        self._tag_stack: List[str] = []
        self._buffer: List[str] = []
        self._title_buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        self._tag_stack.append(tag.lower())
        if tag.lower() in {"pre", "code"}:
            self._buffer = []
        if tag.lower() == "title":
            self._title_buffer = []

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        tag = tag.lower()
        if tag in {"pre", "code"} and self._buffer:
            text = html.unescape("".join(self._buffer)).strip()
            if text and text not in self.code_blocks:
                self.code_blocks.append(text)
            self._buffer = []
        if tag == "title" and self._title_buffer:
            self.title_parts.append(html.unescape("".join(self._title_buffer)).strip())
            self._title_buffer = []
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if any(tag in {"pre", "code"} for tag in self._tag_stack):
            self._buffer.append(data)
        if self._tag_stack and self._tag_stack[-1] == "title":
            self._title_buffer.append(data)


_IMPORT_PATTERNS = [
    re.compile(r"^\s*(from\s+[\w.\-]+\s+import\s+[^\n#]+)", re.MULTILINE),
    re.compile(r"^\s*(import\s+[\w.\-]+(?:\s+as\s+\w+)?)", re.MULTILINE),
    re.compile(r"^\s*(import\s+[^;\n]+\s+from\s+['\"][^'\"]+['\"])", re.MULTILINE),
    re.compile(r"^\s*(const\s+\{?\w+\}?\s*=\s*require\(['\"][^'\"]+['\"]\))", re.MULTILINE),
    re.compile(r"^\s*(import\s+[\w/._\-]+)", re.MULTILINE),
]

_DECORATOR_RE = re.compile(r"^\s*@(?P<decorator>[\w.]+)\s*(?:\([^\n]*\))?", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"```(?P<lang>[\w+.-]*)\n(?P<code>.*?)```", re.DOTALL)


class ExampleExtractor:
    def extract_many(self, pages: Iterable[FetchedPage]) -> List[ExtractedExample]:
        examples: List[ExtractedExample] = []
        seen = set()
        for page in pages:
            if page.error or not page.text_excerpt:
                continue
            for example in self.extract_page(page):
                if example.id not in seen:
                    seen.add(example.id)
                    examples.append(example)
        return sorted(examples, key=lambda e: (e.source_url, e.kind, e.id))

    def extract_page(self, page: FetchedPage) -> List[ExtractedExample]:
        title, blocks = self._extract_structured_blocks(page.text_excerpt, page.content_type)
        examples: List[ExtractedExample] = []
        for idx, (lang, block) in enumerate(blocks):
            cleaned = _normalize_snippet(block)
            if not cleaned:
                continue
            examples.extend(self._examples_from_block(page.source_url, cleaned, lang or _guess_language(cleaned), title, idx))
        if not examples:
            # Fall back to relevant lines from plain text pages.
            lines = _relevant_lines(page.text_excerpt)
            if lines:
                snippet = _normalize_snippet("\n".join(lines[:40]))
                examples.extend(self._examples_from_block(page.source_url, snippet, _guess_language(snippet), title, 0))
        return examples

    def _extract_structured_blocks(self, text: str, content_type: str) -> Tuple[str, List[Tuple[str, str]]]:
        lowered = (content_type or "").lower()
        blocks: List[Tuple[str, str]] = []
        title = ""
        if "html" in lowered:
            parser = _StructuredHTMLParser()
            parser.feed(text)
            title = parser.title_parts[0] if parser.title_parts else ""
            blocks = [("", block) for block in parser.code_blocks]
        for match in _CODE_FENCE_RE.finditer(text):
            blocks.append((match.group("lang"), match.group("code")))
        if not blocks:
            blocks = [("", text)]
        return title, blocks

    def _examples_from_block(self, source_url: str, snippet: str, language: str, title: str, index: int) -> List[ExtractedExample]:
        signals = _detect_signals(snippet)
        examples: List[ExtractedExample] = []
        for import_line in _extract_imports(snippet):
            examples.append(_make_example(source_url, "import_example", language, import_line, ["import"], title, index))
        decorators = [m.group(0).strip() for m in _DECORATOR_RE.finditer(snippet)]
        if decorators:
            examples.append(_make_example(source_url, "decorator_example", language, _focused_snippet(snippet, decorators[0]), ["decorator", *signals], title, index))
        primary_kind = _kind_from_signals(signals)
        emitted = set()
        if primary_kind:
            examples.append(_make_example(source_url, primary_kind, language, snippet, signals, title, index))
            emitted.add(primary_kind)
        # One code block can contain both a component and endpoint sink, or both
        # a route and a test. Emit separate focused semantic examples so the
        # generator can infer multiple rule families from one realistic snippet.
        for semantic_kind in [
            "endpoint_sink",
            "component_usage",
            "constructor_injection",
            "test_target_pattern",
            "provider_factory",
            "route_pattern",
            "object_graph",
        ]:
            if semantic_kind in signals and semantic_kind not in emitted:
                examples.append(_make_example(source_url, semantic_kind, language, snippet, signals, title, index))
                emitted.add(semantic_kind)
        return examples


def _extract_imports(snippet: str) -> List[str]:
    found: List[str] = []
    for pattern in _IMPORT_PATTERNS:
        for match in pattern.finditer(snippet):
            line = match.group(1).strip()
            if line not in found:
                found.append(line)
    return found


def _detect_signals(snippet: str) -> List[str]:
    checks = [
        ("APIRouter", "object_graph"),
        ("include_router", "route_include"),
        ("@router.", "decorator_entrypoint"),
        ("@app.", "decorator_entrypoint"),
        ("Depends(", "constructor_injection"),
        ("providers.Factory", "provider_factory"),
        ("providers.Singleton", "provider_factory"),
        ("fetch(", "endpoint_sink"),
        ("axios.", "endpoint_sink"),
        ("client.get(", "test_target_pattern"),
        ("client.post(", "test_target_pattern"),
        ("TestClient", "test_target_pattern"),
        ("@SpringBootApplication", "decorator_entrypoint"),
        ("@GetMapping", "route_pattern"),
        ("@PostMapping", "route_pattern"),
        ("<", "component_usage"),
        ("useState(", "component_usage"),
        ("gin.Default", "object_graph"),
        ("r.Get(", "route_pattern"),
        ("r.Post(", "route_pattern"),
    ]
    signals = [signal for needle, signal in checks if needle in snippet]
    # Constructor injection in Python services: __init__(..., dep) + self.dep = dep
    if "def __init__(" in snippet and re.search(r"self\.\w+\s*=\s*\w+", snippet):
        signals.append("constructor_injection")
    return sorted(set(signals))


def _kind_from_signals(signals: List[str]) -> str:
    priority = [
        "object_graph",
        "provider_factory",
        "endpoint_sink",
        "decorator_entrypoint",
        "route_pattern",
        "constructor_injection",
        "test_target_pattern",
        "component_usage",
    ]
    for item in priority:
        if item in signals:
            return item
    return ""


def _make_example(source_url: str, kind: str, language: str, snippet: str, signals: List[str], title: str, index: int) -> ExtractedExample:
    normalized = _normalize_snippet(snippet)
    digest = hashlib.sha1(f"{source_url}\n{kind}\n{normalized}".encode("utf-8")).hexdigest()[:12]
    confidence = 0.65 if kind != "import_example" else 0.55
    if "decorator_entrypoint" in signals or "object_graph" in signals or "provider_factory" in signals:
        confidence = 0.75
    return ExtractedExample(
        id=f"ex_{digest}",
        source_url=source_url,
        kind=kind,
        language=language,
        snippet=normalized[:5000],
        signals=sorted(set(signals)),
        confidence=confidence,
        context=title,
    )


def _normalize_snippet(text: str) -> str:
    return "\n".join(line.rstrip() for line in html.unescape(text).strip().splitlines() if line.strip())


def _guess_language(snippet: str) -> str:
    if "from " in snippet and " import " in snippet or "def " in snippet:
        return "python"
    if "import " in snippet and " from " in snippet or "fetch(" in snippet or "axios." in snippet:
        return "typescript"
    if "package " in snippet or "func " in snippet:
        return "go"
    if "public class" in snippet or "@GetMapping" in snippet:
        return "java"
    return "text"


def _relevant_lines(text: str) -> List[str]:
    needles = ["import ", "from ", "@", "APIRouter", "include_router", "fetch(", "axios", "providers.", "TestClient", "Depends("]
    return [line for line in text.splitlines() if any(n in line for n in needles)]


def _focused_snippet(snippet: str, marker: str) -> str:
    lines = snippet.splitlines()
    marker_index = next((i for i, line in enumerate(lines) if marker in line), 0)
    start = max(marker_index - 2, 0)
    end = min(marker_index + 8, len(lines))
    return "\n".join(lines[start:end])


def extract_import_strings(examples: Iterable[ExtractedExample]) -> List[str]:
    imports = []
    for example in examples:
        if example.kind == "import_example" and example.snippet not in imports:
            imports.append(example.snippet)
    return sorted(imports)
