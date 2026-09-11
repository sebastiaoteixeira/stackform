"""Backend code generation context builder (backward compatibility layer).

This module delegates to the builders package for actual implementation.
"""

from .builders import build_context


__all__ = ["build_context"]
