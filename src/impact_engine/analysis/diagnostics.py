"""Structured diagnostics for analysis orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Diagnostic:
    component: str
    severity: str
    code: str
    message: str
    details: Any = None
    actionable: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "component": self.component,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "actionable": self.actionable,
        }
        if self.details is not None:
            data["details"] = self.details
        return data


@dataclass
class DiagnosticsCollector:
    """Collects structured diagnostics while preserving legacy summary keys."""

    legacy: dict[str, Any] = field(default_factory=dict)
    items: list[Diagnostic] = field(default_factory=list)

    def add(
        self,
        key: str,
        message: Any,
        *,
        component: str,
        severity: str = "warning",
        code: str | None = None,
        actionable: bool = False,
        details: Any = None,
    ) -> None:
        self.legacy[key] = message
        self.items.append(
            Diagnostic(
                component=component,
                severity=severity,
                code=code or key,
                message=str(message),
                details=details,
                actionable=actionable,
            )
        )

    def set_legacy(self, key: str, value: Any) -> None:
        self.legacy[key] = value

    def extend_metadata(self, component: str, key: str, values: Any) -> None:
        self.legacy[key] = values
        if isinstance(values, list):
            for item in values:
                self.items.append(
                    Diagnostic(
                        component=component,
                        severity="info",
                        code=key,
                        message=str(item.get("reason") or item.get("message") or item) if isinstance(item, dict) else str(item),
                        details=item,
                    )
                )

    def to_legacy_dict(self) -> dict[str, Any]:
        data = dict(self.legacy)
        data["items"] = [item.to_dict() for item in self.items]
        return data
