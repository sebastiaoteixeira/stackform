"""Structured configuration errors shared by every parsing stage.

Defined here rather than in ``yaml_parser`` so lower-level modules such as
``template_loader`` can import them without a cycle back into the module
that orchestrates the overall parse.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class ConfigError(Exception):
    """One reported problem in a spec.

    Attributes
    ----------
    code:
        Stable machine-readable identifier, e.g. ``"TEMPLATE_UNKNOWN"``.
    message:
        Human-readable description.
    path:
        JSON-pointer-like key path into the merged spec (``"$"`` for the
        document root, dotted otherwise) -- independent of which file
        defined the key, and stable across a document's lifetime.
    location:
        Exact ``file:line:col`` the error was found at, when a source YAML
        file and position are known; ``None`` once a value has been merged
        across files and traced back to no single position.
    hint:
        Optional human-readable suggestion.
    severity:
        ``"error"`` (default) or ``"warning"``.
    """

    code: str
    message: str
    path: str
    location: str | None = None
    hint: str | None = None
    severity: Literal["error", "warning"] = "error"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }
        if self.location:
            payload["location"] = self.location
        if self.hint:
            payload["hint"] = self.hint
        return payload


class ConfigErrors(Exception):
    """One or more :class:`ConfigError`, raised together so every problem is seen at once."""

    def __init__(self, errors: list[ConfigError]):
        super().__init__("configuration has errors")
        self.errors = errors


def format_location(source: Path, mark: Any) -> str:
    """Render a PyYAML mark as the shared ``file:line:col`` location format."""
    return f"{source}:{mark.line + 1}:{mark.column + 1}"


def join_path(parts: tuple[str, ...]) -> str:
    """Render a key-path tuple as the shared dotted, JSON-pointer-like ``path`` format."""
    return ".".join(parts) if parts else "$"
