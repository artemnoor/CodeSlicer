from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .models import ExtractedExample, FetchedPage, ResearchSource, ValidationResult


def build_report(
    library: str,
    ecosystem: str,
    sources: Iterable[ResearchSource],
    pages: Iterable[FetchedPage],
    examples: Iterable[ExtractedExample],
    pack: Dict[str, Any] | None,
    validation: ValidationResult | None,
) -> str:
    sources = list(sources)
    pages = list(pages)
    examples = list(examples)
    lines: List[str] = [
        f"# AI Library Research Report: {library}",
        "",
        f"- Ecosystem: `{ecosystem}`",
        f"- Candidate sources: {len(sources)}",
        f"- Fetched pages/artifacts: {len(pages)}",
        f"- Extracted examples: {len(examples)}",
        "",
        "## Sources used",
    ]
    for source in sources:
        lines.append(f"- `{source.source_type}` official={source.official}: {source.url}")
    lines.extend(["", "## Fetch results"])
    for page in pages:
        status = "error" if page.error else "ok"
        lines.append(f"- {status}: {page.source_url} ({page.bytes_read} bytes){' — ' + page.error if page.error else ''}")
    lines.extend(["", "## Extracted examples"])
    for example in examples[:30]:
        lines.append(f"- `{example.kind}` confidence={example.confidence}: {example.id} from {example.source_url}")
    if len(examples) > 30:
        lines.append(f"- ... {len(examples) - 30} more examples omitted")
    lines.extend(["", "## Inferred rules"])
    if pack:
        for rule in pack.get("rules", []):
            lines.append(f"- `{rule.get('type')}` {rule.get('id')} confidence={rule.get('confidence')}")
        if not pack.get("rules"):
            lines.append("- No rules inferred.")
        diagnostics = pack.get("diagnostics", [])
        if diagnostics:
            lines.extend(["", "## Uncertainty / diagnostics"])
            lines.extend([f"- {item}" for item in diagnostics])
    else:
        lines.append("- No support pack draft generated yet.")
    lines.extend(["", "## Validation"])
    if validation:
        lines.append(f"- Valid: {validation.valid}")
        for err in validation.errors:
            lines.append(f"- Error: {err}")
        for warn in validation.warnings:
            lines.append(f"- Warning: {warn}")
    else:
        lines.append("- Not validated yet.")
    lines.extend(["", "## Recommended next action"])
    if validation and validation.valid:
        lines.append("- Review low-confidence diagnostics, then install the draft support pack into the consuming project.")
    else:
        lines.append("- Use ai_prompt.md and ai_input.json for AI-assisted/manual refinement before installation.")
    return "\n".join(lines) + "\n"
