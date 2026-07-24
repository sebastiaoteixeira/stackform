"""Parser for the v0.3 ``where`` binding form used as a ``given:`` value.

Grammar: ``<collection> where <field> = <rhs> [and <field> = <rhs>]*``. Only the
``=`` operator and ``and`` conjunction are active; the operators reserved by the
v0.3 schema (``!=``, ``<``, ``<=``, ``>``, ``>=``, ``in``) are rejected with a
coded error. A right-hand side is a ``$symbol`` reference, a quoted string, a
number, or a boolean.
"""

from __future__ import annotations

import re

from yaml_api_generator.ir import IRLiteralRef, IRSymbolRef, IRWhereConjunct, WhereRhs
from .yaml_parser import ConfigError

WHERE_KEYWORD = " where "
_AND = " and "
_OPERATOR = re.compile(r"(!=|<=|>=|=|<|>|\bin\b)")
_RESERVED = frozenset({"!=", "<=", ">=", "<", ">", "in"})
_SYMBOL = re.compile(r"^\$([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)$")
_INTEGER = re.compile(r"^-?\d+$")
_DECIMAL = re.compile(r"^-?\d+\.\d+$")


def parse_where_binding(
    raw: str, path: str
) -> tuple[tuple[str, tuple[IRWhereConjunct, ...]] | None, list[ConfigError]]:
    collection, keyword, predicate = raw.partition(WHERE_KEYWORD)
    collection = collection.strip()
    if not keyword or not collection or not predicate.strip():
        return None, [_invalid(raw, path)]

    conjuncts: list[IRWhereConjunct] = []
    for clause in predicate.split(_AND):
        conjunct, errors = _parse_conjunct(clause, raw, path)
        if conjunct is None:
            return None, errors
        conjuncts.append(conjunct)
    return (collection, tuple(conjuncts)), []


def _parse_conjunct(
    clause: str, raw: str, path: str
) -> tuple[IRWhereConjunct | None, list[ConfigError]]:
    match = _OPERATOR.search(clause)
    if match is None:
        return None, [_invalid(raw, path)]

    operator = match.group(1)
    if operator in _RESERVED:
        return None, [ConfigError(
            code="WHERE_OPERATOR_UNSUPPORTED",
            message=(
                f"where operator '{operator}' is reserved but not implemented; "
                "only '=' is active in v0.3"
            ),
            path=path,
        )]

    field = clause[: match.start()].strip()
    rhs_raw = clause[match.end():].strip()
    if not field or not rhs_raw:
        return None, [_invalid(raw, path)]

    rhs, errors = _parse_rhs(rhs_raw, raw, path)
    if rhs is None:
        return None, errors
    return IRWhereConjunct(field=field, rhs=rhs), []


def parse_rhs_value(rhs_raw: str, path: str) -> tuple[WhereRhs | None, list[ConfigError]]:
    """Parse a single right-hand-side value: a $symbol, quoted string, number, or bool."""
    return _parse_rhs(rhs_raw, rhs_raw, path)


def _parse_rhs(
    rhs_raw: str, raw: str, path: str
) -> tuple[WhereRhs | None, list[ConfigError]]:
    symbol = _SYMBOL.match(rhs_raw)
    if symbol is not None:
        root, *rest = symbol.group(1).split(".")
        return IRSymbolRef(root=root, path=tuple(rest)), []
    if len(rhs_raw) >= 2 and rhs_raw[0] == "'" and rhs_raw[-1] == "'":
        return IRLiteralRef(value=rhs_raw[1:-1]), []
    if _INTEGER.match(rhs_raw):
        return IRLiteralRef(value=int(rhs_raw)), []
    if _DECIMAL.match(rhs_raw):
        return IRLiteralRef(value=float(rhs_raw)), []
    if rhs_raw in ("true", "false"):
        return IRLiteralRef(value=rhs_raw == "true"), []
    return None, [ConfigError(
        code="WHERE_RHS_INVALID",
        message=f"invalid right-hand side '{rhs_raw}' in where binding '{raw}'",
        path=path,
        hint="Use a $symbol, a quoted string, a number, or true/false",
    )]


def _invalid(raw: str, path: str) -> ConfigError:
    return ConfigError(
        code="WHERE_BINDING_INVALID",
        message=(
            f"Invalid where binding: '{raw}'. "
            "Expected '<collection> where <field> = <rhs> [and <field> = <rhs>]*'"
        ),
        path=path,
    )
