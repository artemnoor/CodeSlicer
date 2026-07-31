import re
from pathlib import Path

from plugins.frameworks.polyglot_web_common import add_route, join_path, result, source_files


def chi_routes(context, graph):
    routes = 0
    files = list(source_files(Path(context.project_path), (".go",)))
    mounts = {}
    for _rel, text in files:
        for mount in re.finditer(r'\b(?:r|router)\.Mount\s*\(\s*["\']([^"\']+)["\']\s*,\s*([A-Za-z_]\w*)\s*\{\s*\}\s*\.Routes\s*\(\s*\)', text):
            mounts[mount.group(2)] = mount.group(1)
    for rel, text in files:
        route_owners = [(match.start(), match.group(1)) for match in re.finditer(r'func\s*\(\s*\w+\s+([A-Za-z_]\w*)\s*\)\s*Routes\s*\(', text)]
        dynamic_blocks = []
        for group in re.finditer(r'\b(?:r|router)\.Route\s*\(\s*["\']([^"\']*\{[^"\']*)["\']\s*,\s*func\s*\([^)]*\)\s*\{', text):
            depth = 0
            end = None
            for index in range(group.end() - 1, len(text)):
                if text[index] == "{":
                    depth += 1
                elif text[index] == "}":
                    depth -= 1
                    if depth == 0:
                        end = index
                        break
            if end is not None:
                dynamic_blocks.append((group.start(), end))
        for match in re.finditer(r'\b(?:r|router)\.(Get|Post|Put|Patch|Delete)\s*\(\s*["\']([^"\']+)["\']\s*,\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)', text):
            if any(start <= match.start() <= end for start, end in dynamic_blocks):
                continue
            owners = [owner for offset, owner in route_owners if offset <= match.start()]
            owner = owners[-1] if owners else None
            path = join_path(mounts.get(owner, ""), match.group(2))
            # The canonical route model currently collapses ``/items`` and
            # ``/items/{id}`` to one endpoint identity.  Emitting both would
            # downgrade proven handlers to ambiguous edges, so defer
            # parameterized Chi routes until that identity retains parameters.
            if "{" in path or "}" in path:
                continue
            if add_route(graph, framework="chi", language="go", method=match.group(1), path=path, handler=match.group(3), file=rel, line=text.count("\n", 0, match.start()) + 1):
                routes += 1
    return result(graph, "framework.go.chi", "chi", routes)
