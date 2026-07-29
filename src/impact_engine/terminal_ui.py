"""Small, accessible terminal interactions used by the public CLI."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from typing import Any, Callable, TextIO


_PHASES = {
    "preparing": ("Preparing installation", ("◐", "◓", "◑", "◒")),
    "validating": ("Validating package", ("◇", "◈", "◆", "◈")),
    "skills": ("Installing AI skills", ("▖", "▘", "▝", "▗")),
    "support_pack": ("Installing support pack", ("▖", "▘", "▝", "▗")),
    "mcp": ("Configuring MCP connection", ("·  ", "·· ", "···", " ··")),
    "saving": ("Saving local state", ("○", "◌", "●", "◌")),
    "complete": ("Installation complete", ("✓",)),
    "failed": ("Installation needs attention", ("!",)),
}


def _animation_disabled() -> bool:
    """Respect automation and an explicit no-motion preference for terminals."""
    no_motion = os.environ.get("CODESLICER_NO_ANIMATION", "").strip().lower()
    return bool(os.environ.get("CI") or no_motion in {"1", "true", "yes"})


def _human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "calculating ETA"
    seconds = max(0, round(seconds))
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}:{remainder:02d} remaining" if minutes else f"{remainder}s remaining"


class InstallationProgress:
    """A compact live installer panel driven by actual completed operations.

    It intentionally writes to stderr: stdout remains valid JSON for scripts.
    The progress bar is based on the installer's real units of work; ETA is
    shown only after one unit has completed, rather than inventing a duration.
    """

    def __init__(
        self,
        *,
        title: str = "CodeSlicer installer",
        stream: TextIO | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.title = title
        self.stream = stream or sys.stderr
        self.enabled = self.stream.isatty() if enabled is None else enabled
        self.enabled = self.enabled and not _animation_disabled()
        self._color = not bool(os.environ.get("NO_COLOR"))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._drawn = False
        self._started = time.monotonic()
        self._phase = "preparing"
        self._completed = 0
        self._total = 1
        self._message = "Preparing local installation plan"
        self._frame = 0

    def __enter__(self) -> "InstallationProgress":
        if self.enabled:
            self._thread = threading.Thread(target=self._animate, name="codeslicer-install-progress", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        self.close("failed" if exc_type or self._phase == "failed" else "complete")

    def update(self, event: dict[str, Any]) -> None:
        """Receive the installer event emitted immediately around real work."""
        with self._lock:
            self._phase = str(event.get("phase") or "preparing")
            self._completed = max(0, int(event.get("completed", self._completed) or 0))
            self._total = max(1, int(event.get("total", self._total) or 1))
            self._message = str(event.get("message") or self._message)

    def close(self, status: str = "complete") -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.3)
        with self._lock:
            self._phase = status
            if status == "complete":
                self._completed = self._total
                self._message = "Local setup is ready"
            self._render_locked(final=True)
        self.stream.write("\n")
        self.stream.flush()

    def _animate(self) -> None:
        while not self._stop.wait(0.12):
            with self._lock:
                self._frame += 1
                self._render_locked()

    def _render_locked(self, *, final: bool = False) -> None:
        if self._drawn:
            self.stream.write("\x1b[4A")
        self.stream.write("\n".join(f"\r\x1b[2K{line}" for line in self._lines(final=final)))
        self.stream.flush()
        self._drawn = True

    def _lines(self, *, final: bool) -> list[str]:
        label, frames = _PHASES.get(self._phase, _PHASES["preparing"])
        glyph = frames[0] if final else frames[self._frame % len(frames)]
        completed = min(self._completed, self._total)
        width = max(12, min(28, shutil.get_terminal_size((88, 24)).columns - 48))
        filled = round(width * completed / self._total)
        bar = "█" * filled + "░" * (width - filled)
        elapsed = max(0.001, time.monotonic() - self._started)
        eta = None if not completed or completed >= self._total else elapsed / completed * (self._total - completed)
        remaining = self._total - completed
        detail = "ready" if final and self._phase == "complete" else f"{remaining} action{'s' if remaining != 1 else ''} left · {_human_duration(eta)}"
        content_width = max(64, min(94, shutil.get_terminal_size((88, 24)).columns - 2))
        top = f" {self.title} · local-only "
        status = f" {glyph} {label}  [{bar}] {completed:>2}/{self._total:<2}"
        info = f" {self._message} · {detail}"
        lines = [
            f"╭{top}{'─' * max(1, content_width - len(top))}╮",
            f"│{status[:content_width]:<{content_width}}│",
            f"│{info[:content_width]:<{content_width}}│",
            f"╰{'─' * content_width}╯",
        ]
        if not self._color:
            return lines
        color = "31" if self._phase == "failed" else ("36" if self._phase in {"preparing", "validating"} else "32")
        return [f"\x1b[{color}m{line}\x1b[0m" for line in lines]


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
