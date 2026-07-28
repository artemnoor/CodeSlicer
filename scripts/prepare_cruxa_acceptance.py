"""Create a deterministic, read-only review diff for the pinned Cruxa corpus."""
from __future__ import annotations

import argparse
from pathlib import Path


TARGET = Path("backend/src/Cruxa.Api/Features/Routes/RoutesController.cs")
BEFORE = "public async Task<ActionResult<OffsetPaginatedList<RouteDto>>> GetAll([FromQuery] int page = 1, [FromQuery] int pageSize = 20)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.project / TARGET
    lines = source.read_text(encoding="utf-8").splitlines()
    try:
        changed_index = next(index for index, line in enumerate(lines) if line.strip() == BEFORE)
    except StopIteration as exc:
        raise SystemExit(f"Pinned Cruxa fixture changed: expected route handler was not found in {source}") from exc
    before_line = lines[changed_index]
    after_line = before_line.replace("pageSize = 20", "pageSize = 21")
    start = max(0, changed_index - 1)
    end = min(len(lines), changed_index + 2)
    hunk: list[str] = []
    for index in range(start, end):
        if index == changed_index:
            hunk.extend((f"-{before_line}", f"+{after_line}"))
        else:
            hunk.append(f" {lines[index]}")
    line_number = start + 1
    context_count = end - start
    relative = TARGET.as_posix()
    diff = "\n".join((
        f"diff --git a/{relative} b/{relative}",
        f"--- a/{relative}",
        f"+++ b/{relative}",
        f"@@ -{line_number},{context_count} +{line_number},{context_count} @@",
        *hunk,
        "",
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(diff, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
