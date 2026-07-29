"""Fastify literal route registration."""
from __future__ import annotations

import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_route, result, source_files


def fastify_routes(context, graph):
    routes = 0
    pattern = re.compile(r"\b(?:fastify|app|server)\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(?:async\s+)?([A-Za-z_$][\w$]*)", re.I)
    for rel, text in source_files(Path(context.project_path), (".js", ".mjs", ".cjs", ".ts")):
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            if add_route(graph, framework="fastify", language="typescript" if rel.endswith(".ts") else "javascript", method=match.group(1), path=match.group(2), handler=match.group(3), file=rel, line=line):
                routes += 1
        # Fastify's full declaration is common in production applications.
        # Parse one balanced object at a time rather than a whole-file regex;
        # schemas often contain nested JSON objects and comments.
        for start in re.finditer(r"\b(?:fastify|app|server)\.route\s*\(\s*\{", text):
            cursor = start.end() - 1
            depth = 0
            quote = None
            escaped = False
            end = None
            for index in range(cursor, len(text)):
                char = text[index]
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = None
                    continue
                if char in {"'", '\"', "`"}:
                    quote = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            if end is None:
                continue
            declaration = text[cursor:end]
            method = re.search(r"\bmethod\s*:\s*['\"](GET|POST|PUT|PATCH|DELETE)['\"]", declaration, re.I)
            path = re.search(r"\b(?:path|url)\s*:\s*['\"]([^'\"]+)['\"]", declaration)
            handler = re.search(r"\bhandler\s*:\s*([A-Za-z_$][\w$]*)", declaration)
            if not (method and path and handler):
                continue
            if add_route(graph, framework="fastify", language="typescript" if rel.endswith(".ts") else "javascript", method=method.group(1), path=path.group(1), handler=handler.group(1), file=rel, line=text.count("\n", 0, start.start()) + 1):
                routes += 1
    return result(graph, "framework.javascript.fastify", "fastify", routes)
