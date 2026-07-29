"""Evidence-gated Gin route extraction."""
from __future__ import annotations

import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_literal_route, add_route, result, source_files


_ROUTE = re.compile(
    r"\b[A-Za-z_]\w*\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(\s*['\"]([^'\"]+)['\"]",
)
_DIRECT_HANDLER = re.compile(
    r"\(\s*['\"][^'\"]+['\"]\s*,\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*[,)]",
)


def gin_routes(context, graph):
    """Record literal Gin route declarations and exact local handlers."""
    routes = 0
    for rel, text in source_files(Path(context.project_path), (".go",)):
        for match in _ROUTE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            method, path = match.group(1), match.group(2)
            add_literal_route(
                graph, framework="gin", language="go", method=method,
                path=path, file=rel, line=line,
            )
            declaration = text[match.start(): text.find("\n", match.start()) if text.find("\n", match.start()) != -1 else len(text)]
            handler = _DIRECT_HANDLER.search(declaration)
            if handler:
                add_route(
                    graph, framework="gin", language="go", method=method,
                    path=path, handler=handler.group(1), file=rel, line=line,
                )
            routes += 1
    return result(graph, "framework.go.gin", "gin", routes)
