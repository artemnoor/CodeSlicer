"""Deterministic primary-source discovery for library research workflows."""
from typing import Any, Dict


_KNOWN_OFFICIAL_SOURCES: dict[tuple[str, str], dict[str, list[str]]] = {
    ("python", "fastapi"): {
        "docs_urls": [
            "https://fastapi.tiangolo.com/",
            "https://fastapi.tiangolo.com/tutorial/dependencies/",
            "https://fastapi.tiangolo.com/tutorial/bigger-applications/",
            "https://fastapi.tiangolo.com/tutorial/handling-errors/",
            "https://fastapi.tiangolo.com/advanced/events/",
            "https://fastapi.tiangolo.com/advanced/websockets/",
            "https://fastapi.tiangolo.com/advanced/testing/",
        ],
        "github_urls": [
            "https://github.com/fastapi/fastapi",
            "https://github.com/fastapi/fastapi/tree/master/tests",
        ],
    },
    ("python", "httpx"): {
        "docs_urls": [
            "https://www.python-httpx.org/quickstart/",
            "https://www.python-httpx.org/advanced/clients/",
            "https://www.python-httpx.org/async/",
            "https://www.python-httpx.org/api/",
        ],
        "github_urls": [
            "https://github.com/encode/httpx",
            "https://github.com/encode/httpx/tree/master/tests",
        ],
    },
    ("python", "litestar"): {
        "docs_urls": [
            "https://docs.litestar.dev/latest/usage/routing/index.html",
            "https://docs.litestar.dev/main/usage/dependency-injection.html",
        ],
        "github_urls": [
            "https://github.com/litestar-org/litestar",
            "https://github.com/litestar-org/litestar/tree/main/tests",
        ],
    },
    ("python", "dramatiq"): {
        "docs_urls": [
            "https://dramatiq.io/guide.html",
            "https://dramatiq.io/reference.html",
        ],
        "github_urls": [
            "https://github.com/Bogdanp/dramatiq",
            "https://github.com/Bogdanp/dramatiq/tree/master/tests",
        ],
    },
    ("javascript", "ky"): {
        "docs_urls": [
            "https://www.npmjs.com/package/ky",
        ],
        "github_urls": [
            "https://github.com/sindresorhus/ky",
            "https://github.com/sindresorhus/ky/tree/main/source",
        ],
    },
}


def get_candidate_urls(library: str, ecosystem: str) -> Dict[str, Any]:
    """Return a bounded plan of official docs, source and registry evidence.

    Search-result URLs are intentionally excluded: they are not stable evidence
    and can cause a researcher to attribute rules to unrelated projects.
    """
    eco = ecosystem.lower().strip()
    clean_lib = library.replace("@", "").replace("/", "-")
    registry_urls: list[str] = []
    github_urls: list[str] = []
    docs_urls: list[str] = []

    known = _KNOWN_OFFICIAL_SOURCES.get((eco, library.lower()))
    if known:
        docs_urls.extend(known.get("docs_urls", []))
        github_urls.extend(known.get("github_urls", []))

    if eco == "python":
        registry_urls.append(f"https://pypi.org/project/{library}/")
        if not known:
            docs_urls.extend([
                f"https://{clean_lib}.readthedocs.io/en/stable/",
                f"https://{clean_lib}.readthedocs.io/en/latest/",
            ])
            github_urls.append(f"https://github.com/{clean_lib}/{clean_lib}")
    elif eco in ("javascript", "typescript", "npm"):
        registry_urls.append(f"https://www.npmjs.com/package/{library}")
        if not known:
            docs_urls.append(f"https://{clean_lib}.github.io/")
            github_urls.append(f"https://github.com/{clean_lib}/{clean_lib}")
    elif eco == "go":
        registry_urls.append(f"https://pkg.go.dev/{library}")
        docs_urls.append(f"https://pkg.go.dev/{library}?tab=doc")
        github_urls.append(f"https://github.com/{clean_lib}/{clean_lib}")
    else:
        registry_urls.append(f"https://github.com/{clean_lib}/{clean_lib}")

    docs_urls = _unique(docs_urls)
    github_urls = _unique(github_urls)
    registry_urls = _unique(registry_urls)
    return {
        "registry_urls": registry_urls,
        "github_urls": github_urls,
        "docs_urls": docs_urls,
        "source_plan": (
            [{"url": u, "source_type": "official_docs"} for u in docs_urls]
            + [{"url": u, "source_type": "official_repository"} for u in github_urls]
            + [{"url": u, "source_type": "package_registry"} for u in registry_urls]
        ),
    }


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
