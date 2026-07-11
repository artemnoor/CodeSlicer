from __future__ import annotations

from pathlib import Path
from typing import List

from .models import ResearchRequest, ResearchSource


_LOCAL_EXTENSIONS = {".md", ".markdown", ".html", ".htm", ".txt", ".rst"}


def discover_sources(request: ResearchRequest) -> List[ResearchSource]:
    """Return deterministic candidate sources, preferring official pages.

    This function performs no network calls. It combines known registry/docs URL
    patterns with local project fixture pages that can be used offline.
    """

    library = request.library.strip()
    ecosystem = request.ecosystem.strip().lower()
    sources: List[ResearchSource] = []
    sources.extend(_discover_local_sources(request))

    if ecosystem in {"python", "py"}:
        sources.extend(_python_sources(library))
    elif ecosystem in {"javascript", "typescript", "js", "ts", "node"}:
        sources.extend(_javascript_sources(library))
    elif ecosystem == "go":
        sources.extend(_go_sources(library))
    elif ecosystem in {"java", "jvm"}:
        sources.extend(_java_sources(library))
    else:
        slug = _slug(library)
        sources.append(
            ResearchSource(
                url=f"https://github.com/search?q={slug}+examples&type=repositories",
                source_type="github_search",
                title="GitHub candidate search",
                official=False,
                priority=90,
                reason="fallback deterministic GitHub search URL for unknown ecosystem",
            )
        )

    return _dedupe_sorted(sources)


def _discover_local_sources(request: ResearchRequest) -> List[ResearchSource]:
    root = Path(request.project_path or ".")
    if not root.exists():
        return []
    candidates: List[ResearchSource] = []
    search_roots = [root / "docs", root / "research_pages", root / "fixtures", root]
    seen = set()
    for base in search_roots:
        if not base.exists() or not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if len(candidates) >= 8:
                break
            if not path.is_file() or path.suffix.lower() not in _LOCAL_EXTENSIONS:
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            rel = path.resolve().relative_to(root.resolve())
            candidates.append(
                ResearchSource(
                    url=f"local://project/{rel.as_posix()}",
                    source_type="local_project_doc",
                    title=path.name,
                    official=True,
                    priority=5,
                    reason="project-local fixture/documentation page; safe for offline runs",
                    local_path=rel.as_posix(),
                )
            )
    return candidates


def _python_sources(library: str) -> List[ResearchSource]:
    slug = _slug(library)
    known_docs = {
        "fastapi": "https://fastapi.tiangolo.com/",
        "django": "https://docs.djangoproject.com/",
        "flask": "https://flask.palletsprojects.com/",
        "dependency-injector": "https://python-dependency-injector.ets-labs.org/",
    }
    github = {
        "fastapi": "https://github.com/fastapi/fastapi",
        "django": "https://github.com/django/django",
        "flask": "https://github.com/pallets/flask",
        "dependency-injector": "https://github.com/ets-labs/python-dependency-injector",
    }
    sources = [
        ResearchSource(
            url=f"https://pypi.org/project/{slug}/",
            source_type="registry",
            title="PyPI project page",
            official=True,
            priority=10,
            reason="official Python package registry candidate",
        ),
        ResearchSource(
            url=known_docs.get(slug, f"https://{slug}.readthedocs.io/en/latest/"),
            source_type="official_docs",
            title="Official documentation candidate",
            official=True,
            priority=20,
            reason="known official docs URL or deterministic ReadTheDocs candidate",
        ),
        ResearchSource(
            url=github.get(slug, f"https://github.com/search?q={slug}+python+examples&type=repositories"),
            source_type="official_github_or_search",
            title="Official GitHub or GitHub search candidate",
            official=slug in github,
            priority=30,
            reason="official repository when known, otherwise deterministic GitHub search URL",
        ),
    ]
    return sources


def _javascript_sources(library: str) -> List[ResearchSource]:
    slug = _slug(library)
    known_docs = {
        "react": "https://react.dev/",
        "vue": "https://vuejs.org/",
        "next": "https://nextjs.org/docs",
        "axios": "https://axios-http.com/docs/intro",
        "express": "https://expressjs.com/",
    }
    github = {
        "react": "https://github.com/facebook/react",
        "vue": "https://github.com/vuejs/core",
        "next": "https://github.com/vercel/next.js",
        "axios": "https://github.com/axios/axios",
        "express": "https://github.com/expressjs/express",
    }
    return [
        ResearchSource(
            url=f"https://www.npmjs.com/package/{slug}",
            source_type="registry",
            title="npm package page",
            official=True,
            priority=10,
            reason="official npm registry candidate",
        ),
        ResearchSource(
            url=known_docs.get(slug, f"https://{slug}.dev/"),
            source_type="official_docs",
            title="Official documentation candidate",
            official=True,
            priority=20,
            reason="known docs URL or deterministic docs URL guess",
        ),
        ResearchSource(
            url=github.get(slug, f"https://github.com/search?q={slug}+javascript+examples&type=repositories"),
            source_type="official_github_or_search",
            title="Official GitHub or GitHub search candidate",
            official=slug in github,
            priority=30,
            reason="official repository when known, otherwise deterministic GitHub search URL",
        ),
    ]


def _go_sources(library: str) -> List[ResearchSource]:
    slug = _slug(library)
    known = {
        "gin": ("github.com/gin-gonic/gin", "https://github.com/gin-gonic/gin"),
        "chi": ("github.com/go-chi/chi/v5", "https://github.com/go-chi/chi"),
    }
    module_path, repo = known.get(slug, (f"github.com/search?q={slug}+go+framework&type=repositories", f"https://github.com/search?q={slug}+go+examples&type=repositories"))
    pkg_url = f"https://pkg.go.dev/{module_path}" if not module_path.startswith("github.com/search") else "https://pkg.go.dev/search?q=" + slug
    return [
        ResearchSource(pkg_url, "registry", "pkg.go.dev page", True, 10, "official Go package documentation candidate"),
        ResearchSource(repo, "official_github_or_search", "GitHub repository candidate", slug in known, 20, "known official repository or deterministic GitHub search URL"),
    ]


def _java_sources(library: str) -> List[ResearchSource]:
    slug = _slug(library)
    known_docs = {
        "spring": "https://spring.io/projects/spring-framework",
        "spring-framework": "https://docs.spring.io/spring-framework/reference/",
        "spring-boot": "https://docs.spring.io/spring-boot/",
    }
    known_github = {
        "spring": "https://github.com/spring-projects/spring-framework",
        "spring-framework": "https://github.com/spring-projects/spring-framework",
        "spring-boot": "https://github.com/spring-projects/spring-boot",
    }
    return [
        ResearchSource(
            url=f"https://central.sonatype.com/search?q={slug}",
            source_type="registry",
            title="Maven Central candidate",
            official=True,
            priority=10,
            reason="official Maven Central/Sonatype registry search URL",
        ),
        ResearchSource(
            url=known_docs.get(slug, f"https://{slug}.io/docs/"),
            source_type="official_docs",
            title="Official documentation candidate",
            official=True,
            priority=20,
            reason="known official documentation URL or deterministic docs URL guess",
        ),
        ResearchSource(
            url=known_github.get(slug, f"https://github.com/search?q={slug}+java+examples&type=repositories"),
            source_type="official_github_or_search",
            title="Official GitHub or GitHub search candidate",
            official=slug in known_github,
            priority=30,
            reason="official repository when known, otherwise deterministic GitHub search URL",
        ),
    ]


def _slug(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(" ", "-")


def _dedupe_sorted(sources: List[ResearchSource]) -> List[ResearchSource]:
    seen = set()
    result: List[ResearchSource] = []
    for source in sorted(sources, key=lambda s: (s.priority, s.url)):
        if source.url in seen:
            continue
        seen.add(source.url)
        result.append(source)
    return result
