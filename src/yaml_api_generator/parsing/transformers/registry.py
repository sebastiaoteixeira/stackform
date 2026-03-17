from typing import Any

from ...ir import IRDocument
from .v01 import V01Transformer
from .v02 import V02Transformer

_TRANSFORMERS: dict[str, Any] = {
    "0.1": V01Transformer,
    "0.2": V02Transformer,
}


def transform_config(config: dict[str, Any]) -> IRDocument:
    version = str(config.get("version", ""))
    cls = _TRANSFORMERS.get(version)
    if cls is None:
        raise ValueError(f"Unsupported spec version: {version}")
    return cls().transform(config)
