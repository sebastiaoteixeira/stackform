from pathlib import Path
from typing import Any, Callable

from yaml_api_generator.ir import IRDocument
from .v01 import V01Transformer
from .v02 import V02Transformer
from .v03 import V03Transformer

_TRANSFORMERS: dict[str, Callable[[Path], Any]] = {
    "0.1": lambda _spec_dir: V01Transformer(),
    "0.2": lambda _spec_dir: V02Transformer(),
    "0.3": V03Transformer,
}


def transform_config(config: dict[str, Any], spec_dir: Path) -> IRDocument:
    version = str(config.get("version", ""))
    build = _TRANSFORMERS.get(version)
    if build is None:
        raise ValueError(f"Unsupported spec version: {version}")
    return build(spec_dir).transform(config)
