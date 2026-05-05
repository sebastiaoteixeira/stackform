from __future__ import annotations

from pathlib import Path

import yaml

from yaml_api_generator.ir.pack_manifest import (
    OutputConfig,
    Pack,
    PackManifest,
)


def load_pack(name_or_path: str) -> Pack:
    """Load a resource pack by name or path.

    Search order:
    1. If name_or_path is an existing directory path, use it directly
    2. .yaml-api-generator/packs/{name}/
    3. ~/.yaml-api-generator/packs/{name}/
    """
    pack_dir = _resolve_pack_dir(name_or_path)
    manifest = _load_manifest(pack_dir / "pack.yaml")
    templates_dir = pack_dir / "templates"
    if not templates_dir.is_dir():
        raise FileNotFoundError(
            f"Pack '{manifest.name}' is missing templates/ directory: {templates_dir}"
        )
    static_dir = pack_dir / "static"
    hooks_path = pack_dir / "hooks.py"
    return Pack(
        manifest=manifest,
        root_dir=pack_dir,
        templates_dir=templates_dir,
        static_dir=static_dir if static_dir.is_dir() else None,
        hooks_path=hooks_path if hooks_path.is_file() else None,
    )


def _resolve_pack_dir(name_or_path: str) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_dir() and (candidate / "pack.yaml").is_file():
        return candidate.resolve()

    builtin_dir = Path(__file__).parent / "builtin" / name_or_path
    search_dirs = [
        builtin_dir,
        Path.cwd() / ".yaml-api-generator" / "packs" / name_or_path,
        Path.home() / ".yaml-api-generator" / "packs" / name_or_path,
    ]
    for search_dir in search_dirs:
        if search_dir.is_dir() and (search_dir / "pack.yaml").is_file():
            return search_dir.resolve()

    raise FileNotFoundError(
        f"Pack '{name_or_path}' not found. Searched:\n"
        f"  - {candidate}\n"
        + "\n".join(f"  - {d}" for d in search_dirs)
    )


def _load_manifest(manifest_path: Path) -> PackManifest:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Pack manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Pack manifest must be a YAML object: {manifest_path}")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Pack manifest must have a 'name' field: {manifest_path}")

    output_raw = raw.get("output", {})
    dir_struct = output_raw.get("directory_structure", {})

    return PackManifest(
        name=name,
        version=raw.get("version", "0.0.0"),
        language=raw.get("language", "typescript"),
        framework=raw.get("framework", ""),
        template_engine=raw.get("template_engine", "jinja2"),
        description=raw.get("description", ""),
        dependencies=raw.get("dependencies", {}),
        components=raw.get("components", {}),
        scaffold=raw.get("scaffold", []),
        output=OutputConfig(
            extension=output_raw.get("extension", "tsx"),
            generated_dir=dir_struct.get("generated", "src/__generated__"),
            components_dir=dir_struct.get("components", "src/components"),
            pages_dir=dir_struct.get("pages", "src/pages"),
            hooks_dir=dir_struct.get("hooks", "src/__generated__/hooks"),
        ),
        config_schema=raw.get("config_schema", {}),
    )
