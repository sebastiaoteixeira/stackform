from __future__ import annotations

from pathlib import Path

from ..ir import IRDocument
from .context_builder import build_generator_context
from .packs.loader import load_pack
from .renderer import render_templates
from .writer import copy_static, write_output


def generate_frontend(
    ir: IRDocument,
    ui_block: dict,
    output_override: str | None = None,
) -> None:
    frontend = ui_block.get("frontend")
    if not isinstance(frontend, dict):
        raise ValueError("ui.frontend block is required for frontend generation")

    pack_name = frontend.get("pack")
    if not isinstance(pack_name, str) or not pack_name.strip():
        raise ValueError("ui.frontend.pack is required")

    output_dir = Path(output_override or frontend.get("output", "./frontend/src"))
    overwrite = frontend.get("overwrite", "never")

    pack = load_pack(pack_name)
    context = build_generator_context(ir, ui_block, pack.manifest)

    files = render_templates(pack, context)

    written = write_output(files, output_dir, overwrite=overwrite)

    copy_static(pack, output_dir)

    if written:
        for path in written:
            print(f"  {path}")
        print(f"\n{len(written)} file(s) generated in {output_dir}")
    else:
        print("No files generated.")
