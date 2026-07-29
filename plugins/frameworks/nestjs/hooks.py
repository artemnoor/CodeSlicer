"""NestJS controller decorators with literal prefixes and handlers."""
from __future__ import annotations

import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_route, join_path, result, source_files


def nestjs_routes(context, graph):
    routes = 0
    for rel, text in source_files(Path(context.project_path), (".ts", ".tsx")):
        for controller in re.finditer(r"@Controller\s*\(\s*(?:['\"]([^'\"]*)['\"])?\s*\)\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", text):
            prefix, owner = controller.group(1) or "", controller.group(2)
            body = text[controller.end():]
            next_class = re.search(r"\n\s*(?:export\s+)?class\s+", body)
            if next_class:
                body = body[:next_class.start()]
            for route in re.finditer(r"@(Get|Post|Put|Patch|Delete)\s*\(\s*(?:['\"]([^'\"]*)['\"])?\s*\)\s*(?:public\s+|private\s+|protected\s+|async\s+|static\s+)*(?:[\w<>\[\]|?, ]+\s+)?([A-Za-z_$][\w$]*)\s*\(", body):
                line = text.count("\n", 0, controller.end() + route.start()) + 1
                if add_route(graph, framework="nestjs", language="typescript", method=route.group(1), path=join_path(prefix, route.group(2) or ""), handler=route.group(3), file=rel, line=line, owner=owner):
                    routes += 1
    return result(graph, "framework.typescript.nestjs", "nestjs", routes)
