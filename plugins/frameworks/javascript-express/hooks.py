"""Evidence-gated Express route extraction."""
from __future__ import annotations

import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_literal_route, add_route, result, source_files


_ROUTE = re.compile(
    r"\b(?:app|router)\.(get|post|put|patch|delete|head|options)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_DIRECT_HANDLER = re.compile(
    r"\(\s*['\"][^'\"]+['\"]\s*,\s*(?:async\s+)?([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*[,)]",
)


def express_routes(context, graph):
    """Record literal ``app/router.METHOD`` declarations.

    Inline callbacks are genuine local route declarations but do not have a
    canonical named method to attach.  They are intentionally represented as
    ROUTE nodes only; a ROUTE_HANDLES edge is reserved for an exact direct
    identifier in the source.
    """
    routes = 0
    for rel, text in source_files(Path(context.project_path), (".js", ".mjs", ".cjs", ".ts", ".tsx")):
        language = "typescript" if rel.endswith((".ts", ".tsx")) else "javascript"
        for match in _ROUTE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            method, path = match.group(1), match.group(2)
            add_literal_route(
                graph, framework="express", language=language, method=method,
                path=path, file=rel, line=line,
            )
            declaration = text[match.start(): text.find("\n", match.start()) if text.find("\n", match.start()) != -1 else len(text)]
            handler = _DIRECT_HANDLER.search(declaration)
            if handler:
                add_route(
                    graph, framework="express", language=language, method=method,
                    path=path, handler=handler.group(1), file=rel, line=line,
                )
            routes += 1
    return result(graph, "framework.javascript.express", "express", routes)
