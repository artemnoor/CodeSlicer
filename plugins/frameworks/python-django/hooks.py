"""Django registration candidates; intentionally not a type resolver."""
from __future__ import annotations

import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_framework_candidate, result, source_files


_URL = re.compile(r"\b(?:path|re_path)\s*\(\s*[^,]+,\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)(?:\.as_view\s*\(\s*\))?")
_QUERY = re.compile(r"\b([A-Za-z_]\w*)\.(?:objects|_default_manager)\.(filter|get|exclude|annotate|select_related)\s*\(")


def django_candidates(context, graph):
    registrations = 0
    queries = 0
    for rel, text in source_files(Path(context.project_path), (".py",)):
        for match in _URL.finditer(text):
            registrations += 1
            add_framework_candidate(
                graph, framework="django", language="python", registration="path/re_path",
                handler=match.group(1), file=rel, line=text.count("\n", 0, match.start()) + 1,
            )
        queries += len(_QUERY.findall(text))
    plugin_result = result(graph, "framework.python.django", "django", registrations)
    graph.metadata.setdefault("polyglot_framework_features", {}).setdefault("django", {}).update({
        "status": "limited", "url_candidates": registrations, "queryset_candidates": queries,
        "note": "Django URL and QuerySet semantics are candidate evidence until Python type/framework resolution validates them.",
    })
    return plugin_result
