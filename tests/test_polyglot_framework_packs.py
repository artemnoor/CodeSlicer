"""Regression gates for optional popular-framework packs.

Each case has dependency/import activation, a literal framework declaration,
and a local handler.  The negative check ensures a missing handler produces no
route edge, preserving CodeSlicer's evidence-gated contract.
"""
from __future__ import annotations

import json

import pytest

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument


CASES = [
    (
        "nestjs", "package.json", json.dumps({"dependencies": {"@nestjs/common": "^11.0.0"}}), "src/cats.controller.ts",
        "import { Controller, Get } from '@nestjs/common';\n@Controller('cats')\nexport class CatsController {\n  @Get('featured')\n  featured() { return []; }\n}\n",
        "framework.typescript.nestjs", "HTTP GET /cats/featured", "featured", "ROUTE_HANDLES",
    ),
    (
        "fastify", "package.json", json.dumps({"dependencies": {"fastify": "^5.0.0"}}), "src/routes.js",
        "import Fastify from 'fastify';\nconst fastify = Fastify();\nfunction listBooks() { return []; }\nfastify.route({ method: 'GET', path: '/books', handler: listBooks, schema: { response: {} } });\n",
        "framework.javascript.fastify", "HTTP GET /books", "listBooks", "ROUTE_HANDLES",
    ),
    (
        "chi", "go.mod", "module example.com/chi\nrequire github.com/go-chi/chi/v5 v5.0.0\n", "main.go",
        "package main\nimport \"github.com/go-chi/chi/v5\"\nfunc List(w int) {}\nfunc main() { r := chi.NewRouter(); r.Get(\"/books\", List) }\n",
        "framework.go.chi", "HTTP GET /books", "List", "ROUTE_HANDLES",
    ),
    (
        "echo", "go.mod", "module example.com/echo\nrequire github.com/labstack/echo/v4 v4.0.0\n", "main.go",
        "package main\nimport \"github.com/labstack/echo/v4\"\nfunc List(c int) error { return nil }\nfunc main() { e := echo.New(); e.GET(\"/books\", List) }\n",
        "framework.go.echo", "HTTP GET /books", "List", "ROUTE_HANDLES",
    ),
    (
        "fiber", "go.mod", "module example.com/fiber\nrequire github.com/gofiber/fiber/v2 v2.0.0\n", "main.go",
        "package main\nimport \"github.com/gofiber/fiber/v2\"\nfunc List(c int) error { return nil }\nfunc main() { app := fiber.New(); app.Get(\"/books\", List) }\n",
        "framework.go.fiber", "HTTP GET /books", "List", "ROUTE_HANDLES",
    ),
    (
        "jaxrs", "pom.xml", "<project><dependencies><dependency><groupId>jakarta.ws.rs</groupId></dependency></dependencies></project>", "src/main/java/example/BooksResource.java",
        "package example;\nimport jakarta.ws.rs.*;\n@Path(\"/books\")\npublic class BooksResource {\n  @GET @Path(\"/featured\") @Produces(\"application/json\")\n  public String featured() { return \"ok\"; }\n}\n",
        "framework.java.jaxrs", "HTTP GET /books/featured", "featured", "ROUTE_HANDLES",
    ),
    (
        "micronaut", "pom.xml", "<project><dependencies><dependency><groupId>io.micronaut</groupId></dependency></dependencies></project>", "src/main/java/example/BooksController.java",
        "package example;\nimport io.micronaut.http.annotation.*;\n@Controller(\"/books\") // endpoint group\npublic class BooksController {\n  @Get(\"/featured\") // endpoint\n  public String featured() { return \"ok\"; }\n}\n",
        "framework.java.micronaut", "HTTP GET /books/featured", "featured", "ROUTE_HANDLES",
    ),
    (
        "refit", "Client.csproj", "<Project><ItemGroup><ProjectReference Include=\"../Refit/Refit.csproj\" /></ItemGroup></Project>", "BooksClient.cs",
        "using Refit;\npublic interface IBooksClient {\n [Get(\"/books/{id}\")]\n string GetBook(string id);\n}\n",
        "framework.csharp.refit", "HTTP GET /books/{id}", "GetBook", "HTTP_CALLS",
    ),
]


@pytest.mark.parametrize(("name", "manifest", "manifest_text", "source_path", "source", "pack_id", "route_id", "handler", "edge_kind"), CASES)
def test_popular_framework_pack_emits_only_literal_handler_evidence(tmp_path, name, manifest, manifest_text, source_path, source, pack_id, route_id, handler, edge_kind):
    (tmp_path / manifest).write_text(manifest_text, encoding="utf-8")
    file = tmp_path / source_path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(source, encoding="utf-8")

    graph = GraphDocument.from_dict(analyze_project_core(str(tmp_path), create_research_requests=False)["graph"])
    selected = {item["id"] for item in graph.metadata["plugin_selection_plan"]["selected"]}
    assert pack_id in selected
    route_edges = [edge for edge in graph.edges if edge.kind == edge_kind and route_id in {edge.from_node, edge.to_node}]
    assert route_edges, f"{name}: literal framework contract was not represented"
    assert any(handler == graph.get_node(edge.to_node if edge.from_node == route_id else edge.from_node).name for edge in route_edges)
    assert all(edge.properties.get("resolution_status") == "resolved_exact" and edge.evidence for edge in route_edges)


def test_nestjs_incomplete_decorator_is_not_invented(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"@nestjs/common": "^11.0.0"}}), encoding="utf-8")
    source = tmp_path / "src" / "books.controller.ts"
    source.parent.mkdir()
    source.write_text("import { Controller, Get } from '@nestjs/common';\n@Controller('books')\nexport class BooksController { @Get() /* no following method declaration */ }\n", encoding="utf-8")
    graph = GraphDocument.from_dict(analyze_project_core(str(tmp_path), create_research_requests=False)["graph"])
    assert not any(edge.kind == "ROUTE_HANDLES" and edge.from_node == "HTTP GET /books" for edge in graph.edges)


def test_jaxrs_pack_activates_from_a_qualified_import_without_dependency_declaration(tmp_path):
    """BOM-managed projects may expose the API only through source imports."""
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    source = tmp_path / "src/main/java/example/HealthResource.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import jakarta.ws.rs.GET;\nimport jakarta.ws.rs.Path;\n"
        "@Path(\"/health\") public class HealthResource {\n"
        "  @GET public String status() { return \"ok\"; }\n}\n",
        encoding="utf-8",
    )
    graph = GraphDocument.from_dict(analyze_project_core(str(tmp_path), create_research_requests=False)["graph"])
    selected = {item["id"] for item in graph.metadata["plugin_selection_plan"]["selected"]}
    assert "framework.java.jaxrs" in selected
    assert any(edge.kind == "ROUTE_HANDLES" and edge.from_node == "HTTP GET /health" for edge in graph.edges)


def test_chi_literal_mount_composes_a_resource_routes_prefix(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/chi\nrequire github.com/go-chi/chi/v5 v5.0.0\n", encoding="utf-8")
    (tmp_path / "main.go").write_text(
        "package main\nimport \"github.com/go-chi/chi/v5\"\n"
        "func main() { r := chi.NewRouter(); r.Mount(\"/api\", booksResource{}.Routes()) }\n",
        encoding="utf-8",
    )
    (tmp_path / "books.go").write_text(
        "package main\nimport \"github.com/go-chi/chi/v5\"\n"
        "type booksResource struct{}\nfunc (rs booksResource) Routes() chi.Router { r := chi.NewRouter(); r.Get(\"/books\", rs.List); return r }\n"
        "func (rs booksResource) List() {}\n",
        encoding="utf-8",
    )
    graph = GraphDocument.from_dict(analyze_project_core(str(tmp_path), create_research_requests=False)["graph"])
    assert any(edge.kind == "ROUTE_HANDLES" and edge.from_node == "HTTP GET /api/books" and edge.properties.get("resolution_status") == "resolved_exact" for edge in graph.edges)
