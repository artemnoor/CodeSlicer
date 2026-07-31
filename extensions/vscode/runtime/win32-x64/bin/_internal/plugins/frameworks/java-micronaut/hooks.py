import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_route, join_path, result, source_files


def micronaut_routes(context, graph):
    routes = 0
    controller_pattern = re.compile(r'@Controller\s*\(\s*["\']([^"\']*)["\']\s*\)\s*(?://[^\n]*)?\s*(?:public\s+)?class\s+([A-Za-z_]\w*)')
    route_pattern = re.compile(
        r'@(Get|Post|Put|Patch|Delete)\s*\(\s*(?:["\']([^"\']*)["\'])?\s*\)'
        r'(?:\s*@[\w.]+\s*(?:\([^)]*\))?\s*)*\s*(?://[^\n]*)?\s*'
        r'(?:public\s+)?[\w<>?,.\[\] ]+\s+([A-Za-z_]\w*)\s*\('
    )
    for rel, text in source_files(Path(context.project_path), (".java",)):
        for controller in controller_pattern.finditer(text):
            body = text[controller.end():]
            for route in route_pattern.finditer(body):
                if add_route(graph, framework="micronaut", language="java", method=route.group(1), path=join_path(controller.group(1), route.group(2) or ""), handler=route.group(3), file=rel, line=text.count("\n", 0, controller.end() + route.start()) + 1, owner=controller.group(2)):
                    routes += 1
    return result(graph, "framework.java.micronaut", "micronaut", routes)
