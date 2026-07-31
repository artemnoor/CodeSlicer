"""Refit attributes are explicit client HTTP contract evidence."""
from __future__ import annotations

import re
from pathlib import Path

from impact_engine.models import Node
from plugins.frameworks.polyglot_web_common import add_route, result, source_files


def refit_contracts(context, graph):
    routes = 0
    pattern = re.compile(r"\[\s*(Get|Post|Put|Patch|Delete)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\]\s*(?:public\s+)?[\w<>?,.\[\] ]+\s+([A-Za-z_]\w*)\s*\(")
    for rel, text in source_files(Path(context.project_path), (".cs",)):
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            # Interfaces are contracts and may not be emitted as METHOD by the
            # generic C# extractor.  This pack owns the explicit attribute +
            # declaration fact, so materialize a local method only from those
            # two adjacent source constructs.
            if not any(node.kind == "METHOD" and node.name == match.group(3) and node.properties.get("file") == rel for node in graph.nodes):
                graph.add_node(Node(f"refit:{rel}:{match.group(3)}", "METHOD", match.group(3), {"file": rel, "line": line, "language": "csharp", "framework": "refit", "contract_method": True}))
            if add_route(graph, framework="refit", language="csharp", method=match.group(1), path=match.group(2), handler=match.group(3), file=rel, line=line, edge_kind="HTTP_CALLS", direction="handler_to_route", confidence=0.9):
                routes += 1
    return result(graph, "framework.csharp.refit", "refit", routes)
