"""AI Library Researcher request workflow. Stage 9 complete."""
from pathlib import Path


def sanitize_path_segment(val: str) -> str:
    # Replace unsafe characters
    for char in ['/', '\\', ' ', '<', '>', '=', ':', '*', '?', '"', '|']:
        val = val.replace(char, "_")
    # Reduce consecutive underscores
    while "__" in val:
        val = val.replace("__", "_")
    return val.strip("_")


def create_research_request(
    library_name: str,
    version: str = "unknown",
    package_manager: str = "unknown",
    language: str = "python",
    imports: list[str] | None = None,
    usages: list[str] | None = None,
    official_docs: list[str] | None = None,
) -> dict:
    safe_version = sanitize_path_segment(version) if version else "unknown"
    if not safe_version:
        safe_version = "unknown"
        
    output_path = f"support_packs/{library_name}/{safe_version}/support_pack.json"
    
    imports_list = imports or []
    usages_list = usages or []
    docs_list = official_docs or []
    
    instructions = f"""Research library {library_name} version {version} for {language} using package manager {package_manager}.
Use official documentation, official GitHub repository, and official GitHub examples first.

Required Tasks:
1. Search official documentation first.
2. Search official GitHub repository/examples.
3. Extract semantic patterns.
4. Output a machine-readable support_pack.json that identifies route decorators, providers, dependencies, etc.
5. Include sources, patterns, edge_rules, confidence_rules, playground_cases, and limitations.
6. Do not return prose only.

Forbid:
- Prose-only answers.
- Unverified rules.
- Real code changes to the resolver.
- Claiming official status without validation.

Context:
- Detected imports: {imports_list}
- Detected usages: {usages_list}
- Known official docs links: {docs_list}
"""

    return {
        "library_name": library_name,
        "version": version,
        "package_manager": package_manager,
        "language": language,
        "imports": imports_list,
        "usages": usages_list,
        "official_docs": docs_list,
        "output_path": output_path,
        "instructions": instructions
    }


def create_research_request_from_unknown_library(library_name: str, detected_imports: list[str]) -> dict:
    return create_research_request(
        library_name=library_name,
        imports=detected_imports
    )
