import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_route, join_path, result, source_files


def jaxrs_routes(context, graph):
    routes = 0
    controller_pattern = re.compile(r'@Path\s*\(\s*["\']([^"\']*)["\']\s*\)\s*(?://[^\n]*)?\s*(?:public\s+)?class\s+([A-Za-z_]\w*)')
    route_pattern = re.compile(
        r'@(GET|POST|PUT|PATCH|DELETE)\b'
        r'(?P<annotations>(?:\s*@[\w.]+\s*(?:\([^)]*\))?\s*)*)\s*(?://[^\n]*)?\s*'
        r'(?:public\s+)?[\w<>?,.\[\] ]+\s+([A-Za-z_]\w*)\s*\('
    )
    for rel, text in source_files(Path(context.project_path), (".java",)):
        for controller in controller_pattern.finditer(text):
            body = text[controller.end():]
            for route in route_pattern.finditer(body):
                path_match = re.search(r'@Path\s*\(\s*["\']([^"\']*)["\']\s*\)', route.group("annotations"))
                if add_route(graph, framework="jaxrs", language="java", method=route.group(1), path=join_path(controller.group(1), path_match.group(1) if path_match else ""), handler=route.group(3), file=rel, line=text.count("\n", 0, controller.end() + route.start()) + 1, owner=controller.group(2)):
                    routes += 1
    return result(graph, "framework.java.jaxrs", "jaxrs", routes)
