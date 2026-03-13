from pathlib import Path

from ..parser import load_and_generate_ir
from .context_builder import build_context
from .generators.base import CodeGenerator
from .generators.fastapi.generator import FastAPIGenerator
from .generators.drf.generator import DRFGenerator
from .generators.raw.generator import RawASGIGenerator


_GENERATORS: dict[str, type[CodeGenerator]] = {
    "fastapi": FastAPIGenerator,
    "drf": DRFGenerator,
    "raw": RawASGIGenerator,
}


def compile_api(
    yaml_file: str | Path,
    schema_file: str | Path,
    output_dir: str | Path,
    target: str = "fastapi",
) -> None:
    generator_cls = _GENERATORS.get(target)
    if generator_cls is None:
        supported = ", ".join(_GENERATORS)
        raise ValueError(f"Unknown target '{target}'. Supported: {supported}")

    ir = load_and_generate_ir(yaml_file, schema_file)
    context = build_context(ir)
    generator = generator_cls()
    generator.generate(context, Path(output_dir))
