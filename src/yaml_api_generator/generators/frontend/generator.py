from __future__ import annotations

import logging
from pathlib import Path

from yaml_api_generator.ir import IRDocument
from yaml_api_generator.ir.ui import GeneratorContext
from .packs.loader import load_pack
from .renderer import render_templates
from .writer import copy_static, write_output

logger = logging.getLogger(__name__)


def generate_frontend(
    ir: IRDocument,
    ui: GeneratorContext,
    pack_name: str,
    output_override: str | None = None,
    overwrite: str = "never",
) -> None:
    output_dir = Path(output_override or "./frontend")

    pack = load_pack(pack_name)

    files = render_templates(pack, ui)

    written = write_output(files, output_dir, overwrite=overwrite)

    copy_static(pack, output_dir)

    if written:
        for path in written:
            logger.info("  %s", path)
        logger.info("%d file(s) generated in %s", len(written), output_dir)
    else:
        logger.info("No files generated.")
