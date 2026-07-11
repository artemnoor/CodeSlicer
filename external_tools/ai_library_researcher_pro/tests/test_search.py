from ai_library_researcher_pro.models import ResearchRequest
from ai_library_researcher_pro.search import discover_sources


def urls_for(library: str, ecosystem: str):
    return [s.url for s in discover_sources(ResearchRequest(library=library, ecosystem=ecosystem))]


def test_source_discovery_python_fastapi():
    urls = urls_for("fastapi", "python")
    assert "https://pypi.org/project/fastapi/" in urls
    assert "https://fastapi.tiangolo.com/" in urls
    assert "https://github.com/fastapi/fastapi" in urls


def test_source_discovery_javascript_react():
    urls = urls_for("react", "javascript")
    assert "https://www.npmjs.com/package/react" in urls
    assert "https://react.dev/" in urls
    assert "https://github.com/facebook/react" in urls


def test_source_discovery_go_gin_or_chi():
    gin_urls = urls_for("gin", "go")
    chi_urls = urls_for("chi", "go")
    assert "https://pkg.go.dev/github.com/gin-gonic/gin" in gin_urls
    assert "https://github.com/gin-gonic/gin" in gin_urls
    assert "https://pkg.go.dev/github.com/go-chi/chi/v5" in chi_urls
    assert "https://github.com/go-chi/chi" in chi_urls


def test_source_discovery_java_spring():
    urls = urls_for("spring", "java")
    assert "https://central.sonatype.com/search?q=spring" in urls
    assert "https://spring.io/projects/spring-framework" in urls
    assert "https://github.com/spring-projects/spring-framework" in urls
