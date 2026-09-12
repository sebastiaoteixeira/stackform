"""Uniform undefined-symbol enforcement for v0.3 symbol resolution.

Every ``$<symbol>`` reference resolves against the names bound in its scope. A
scope carries the set of bound names and a human-readable label; resolving a
name that nothing bound yields a single coded error naming the symbol and the
scope. Each v0.3 resolution site (``when`` operands, repository filters, and --
in later issues -- ``where`` bindings, service ``with``, controller ``bind``)
builds a scope and defers to it, so the rule is enforced identically everywhere.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from yaml_api_generator.parsers.yaml_parser import ConfigError

UNDEFINED_SYMBOL = "UNDEFINED_SYMBOL"


@dataclass(frozen=True)
class SymbolScope:
    """A resolution scope: the names bound in it plus a label for diagnostics."""

    label: str
    bound: frozenset[str] = frozenset()

    def undefined(self, symbols: Iterable[str], path: str) -> list[ConfigError]:
        return [
            ConfigError(
                code=UNDEFINED_SYMBOL,
                message=f"symbol ${name} is not bound in scope {self.label}",
                path=path,
            )
            for name in sorted(set(symbols))
            if name not in self.bound
        ]
