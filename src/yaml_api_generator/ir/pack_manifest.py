from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NO_CONFIG: dict[str, Any] = {"type": "object", "additionalProperties": False}


@dataclass
class OutputConfig:
    extension: str = "tsx"
    generated_dir: str = "src/__generated__"
    components_dir: str = "src/components"
    pages_dir: str = "src/pages"
    hooks_dir: str = "src/__generated__/hooks"


@dataclass
class PackManifest:
    name: str
    version: str
    language: str = "typescript"
    framework: str = ""
    template_engine: str = "jinja2"
    description: str = ""
    dependencies: dict[str, str] = field(default_factory=dict)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    scaffold: list[str] = field(default_factory=list)
    output: OutputConfig = field(default_factory=OutputConfig)
    config_schema: dict[str, Any] = field(default_factory=lambda: NO_CONFIG)


@dataclass
class Pack:
    manifest: PackManifest
    root_dir: Path
    templates_dir: Path
    static_dir: Path | None
    hooks_path: Path | None
