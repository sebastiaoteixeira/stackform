from __future__ import annotations

import shutil
from pathlib import Path

from .output import OutputFile
from .packs.manifest import Pack


def write_output(
    files: list[OutputFile],
    output_dir: Path,
    overwrite: str = "never",
) -> list[str]:
    """Write output files respecting zone and overwrite policy.

    Returns list of written file paths (relative).
    """
    written: list[str] = []
    for file in files:
        target = output_dir / file.path
        if file.zone == "generated":
            _write_file(target, file.content)
            written.append(file.path)
        elif file.zone == "editable":
            if overwrite == "always":
                _write_file(target, file.content)
                written.append(file.path)
            elif overwrite == "never":
                if not target.exists():
                    _write_file(target, file.content)
                    written.append(file.path)
    return written


def copy_static(pack: Pack, output_dir: Path) -> None:
    """Copy pack's static/ directory into the generated output."""
    if pack.static_dir is None:
        return
    dest = output_dir / pack.manifest.output.generated_dir
    for src_file in pack.static_dir.rglob("*"):
        if not src_file.is_file():
            continue
        relative = src_file.relative_to(pack.static_dir)
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, target)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
