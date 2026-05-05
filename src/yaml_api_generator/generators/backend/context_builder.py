"""Backend code generation context builder (backward compatibility layer).

This module delegates to the builders package for actual implementation.
"""

from yaml_api_generator.ir import IRDocument
from .compile_context import CompileContext
from .builders import build_context


__all__ = ["build_context"]


def build_context(document: IRDocument) -> CompileContext:
    """Build compilation context from IR document.

    Args:
        document: Complete IR document

    Returns:
        Compilation context for code generation
    """
    from .builders import build_context as _build_context

    return _build_context(document)
