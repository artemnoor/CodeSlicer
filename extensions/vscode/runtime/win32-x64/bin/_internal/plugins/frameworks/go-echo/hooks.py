import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_route, result, source_files


def echo_routes(context, graph):
    routes = 0
    for rel, text in source_files(Path(context.project_path), (".go",)):
        for match in re.finditer(r'\b(?:e|echo)\.(GET|POST|PUT|PATCH|DELETE)\s*\(\s*["\']([^"\']+)["\']\s*,\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)', text):
            if add_route(graph, framework="echo", language="go", method=match.group(1), path=match.group(2), handler=match.group(3), file=rel, line=text.count("\n", 0, match.start()) + 1):
                routes += 1
    return result(graph, "framework.go.echo", "echo", routes)
