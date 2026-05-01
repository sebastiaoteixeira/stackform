from pathlib import Path

from yaml_api_generator.generators.frontend.generator import generate_frontend
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.base import CodeGenerator
from yaml_api_generator.generators.backend.fastapi import FastAPIGenerator
from yaml_api_generator.generators.backend.drf import DRFGenerator
from yaml_api_generator.generators.backend.raw import RawASGIGenerator


_GENERATORS: dict[str, type[CodeGenerator]] = {
    "fastapi": FastAPIGenerator,
    "drf": DRFGenerator,
    "raw": RawASGIGenerator,
}

# TODO: 
def compile_api(
    yaml_file: str | Path,
    schema_file: str | Path | None = None,
    output_dir: str | Path = "./target",
    target: str = "fastapi",
) -> None:
    generator_cls = _GENERATORS.get(target)
    if generator_cls is None:
        supported = ", ".join(_GENERATORS)
        raise ValueError(f"Unknown target '{target}'. Supported: {supported}")

    result = load_and_generate_ir(yaml_file, schema_file)
    out = Path(output_dir)
    context = build_context(result.ir)
    generator = generator_cls()
    generator.generate(context, out / "backend")

    if result.ui_block is not None:
        from yaml_api_generator.parsers.ui_parser import build_generator_context

        frontend_block = result.ui_block.get("frontend", {}) or {}
        pack_name = frontend_block.get("pack")
        if not isinstance(pack_name, str) or not pack_name.strip():
            raise ValueError("ui.frontend.pack is required")

        overwrite = frontend_block.get("overwrite", "never")

        from yaml_api_generator.generators.frontend.packs.loader import load_pack
        pack = load_pack(pack_name)
        ui = build_generator_context(result.ir, result.ui_block, pack.manifest)

        generate_frontend(
            ir=result.ir,
            ui=ui,
            pack_name=pack_name,
            output_override=str(out / "frontend"),
            overwrite=overwrite,
        )
