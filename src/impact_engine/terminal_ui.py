"""Small, accessible terminal interactions used by the public CLI."""
from __future__ import annotations

from typing import Any, Callable


def choose_agent_clients(catalog: dict[str, dict[str, Any]], detected: list[dict[str, Any]]) -> list[str]:
    """Choose one or more AI clients with a keyboard-first checkbox menu.

    The normal path uses Questionary: arrows move, Space toggles and Enter
    confirms.  The plain-text fallback keeps the installer usable if a
    partially upgraded environment is missing its new dependency.
    """
    detected_ids = {item["id"] for item in detected}
    confidence = {item["id"]: item["confidence"] for item in detected}
    entries = [
        {
            "id": client_id,
            "title": f"{item['display_name']}  [{confidence.get(client_id, item['status'])}]",
            "checked": client_id in detected_ids,
        }
        for client_id, item in catalog.items()
    ]
    try:
        import questionary
        from prompt_toolkit.styles import Style
    except ImportError:
        return _numbered_client_fallback(entries)

    answer = questionary.checkbox(
        "Choose IDEs to configure",
        choices=[questionary.Choice(entry["title"], value=entry["id"], checked=entry["checked"]) for entry in entries],
        instruction="↑/↓ move  •  Space select  •  Enter install",
        qmark="✦",
        style=Style.from_dict({
            "qmark": "fg:#5fd7ff bold",
            "question": "bold",
            "pointer": "fg:#5fd7ff bold",
            "selected": "fg:#5fd7ff",
            "instruction": "fg:#808080",
        }),
    ).ask()
    if answer is None or not answer:
        raise ValueError("client selection cancelled")
    return list(dict.fromkeys(answer))


def _numbered_client_fallback(entries: list[dict[str, Any]], input_fn: Callable[[str], str] = input) -> list[str]:
    """Compatibility fallback for a broken or partially installed CLI."""
    print("Choose an integration:")
    for index, entry in enumerate(entries, start=1):
        marker = "*" if entry["checked"] else " "
        print(f"[{index}] {marker} {entry['title']}")
    selected = input_fn("Select IDEs to configure (for example 1,3; empty cancels): ").strip()
    if not selected:
        raise ValueError("client selection cancelled")
    try:
        return list(dict.fromkeys(entries[int(value.strip()) - 1]["id"] for value in selected.split(",")))
    except (IndexError, ValueError) as exc:
        raise ValueError("invalid client selection") from exc
