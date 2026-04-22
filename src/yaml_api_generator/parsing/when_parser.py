from __future__ import annotations

import re

from ..when_ast import (
    And,
    Equals,
    FieldRef,
    NotEquals,
    StringLiteral,
    WhenExpr,
)
from .parser import ConfigError


_STRING_LITERAL_RE = re.compile(r"^'([^']*)'$")
_FIELD_REF_RE = re.compile(r"^(principal|document)(\.\w+)+$")


def _parse_operand(raw: str, path: str) -> tuple[WhenExpr | None, ConfigError | None]:
    raw = raw.strip()
    m = _STRING_LITERAL_RE.match(raw)
    if m:
        return StringLiteral(value=m.group(1)), None

    m = _FIELD_REF_RE.match(raw)
    if m:
        parts = raw.split(".")
        return FieldRef(root=parts[0], path=tuple(parts[1:])), None

    return None, ConfigError(
        code="WHEN_OPERAND_INVALID",
        message=f"Invalid operand: '{raw}'. Expected a field reference (principal.*/document.*) or a string literal ('...')",
        path=path,
    )


def parse_when_expr(raw: str, path: str) -> tuple[WhenExpr | None, list[ConfigError]]:
    errors: list[ConfigError] = []

    # Try 'not equals' first (longer match)
    sep = " not equals "
    idx = raw.find(sep)
    if idx != -1:
        lhs_raw = raw[:idx]
        rhs_raw = raw[idx + len(sep):]
        lhs, err = _parse_operand(lhs_raw, path)
        if err:
            errors.append(err)
        rhs, err = _parse_operand(rhs_raw, path)
        if err:
            errors.append(err)
        if errors:
            return None, errors
        return NotEquals(left=lhs, right=rhs), []

    sep = " equals "
    idx = raw.find(sep)
    if idx != -1:
        lhs_raw = raw[:idx]
        rhs_raw = raw[idx + len(sep):]
        lhs, err = _parse_operand(lhs_raw, path)
        if err:
            errors.append(err)
        rhs, err = _parse_operand(rhs_raw, path)
        if err:
            errors.append(err)
        if errors:
            return None, errors
        return Equals(left=lhs, right=rhs), []

    return None, [
        ConfigError(
            code="WHEN_EXPR_INVALID",
            message=f"Invalid when expression: '{raw}'. Expected '<operand> equals <operand>' or '<operand> not equals <operand>'",
            path=path,
        )
    ]


def parse_when_list(
    raw: str | list[str], path: str
) -> tuple[WhenExpr | None, list[ConfigError]]:
    """Parse a single when string or a list of when strings (AND-ed together)."""
    if isinstance(raw, str):
        return parse_when_expr(raw, path)

    if not raw:
        return None, []

    exprs: list[WhenExpr] = []
    errors: list[ConfigError] = []
    for i, item in enumerate(raw):
        expr, errs = parse_when_expr(item, f"{path}[{i}]")
        errors.extend(errs)
        if expr is not None:
            exprs.append(expr)

    if errors:
        return None, errors

    result = exprs[0]
    for expr in exprs[1:]:
        result = And(left=result, right=expr)
    return result, []


def parse_document_binding(
    raw: str, path: str
) -> tuple[tuple[str, str | None] | None, list[ConfigError]]:
    """Parse document binding: '<collection>' or '<collection> by <param>'.

    Returns (collection, id_param) or None on error.
    """
    raw = raw.strip()
    parts = raw.split(" by ", 1)
    if len(parts) == 2:
        collection = parts[0].strip()
        id_param = parts[1].strip()
        if not collection or not id_param:
            return None, [
                ConfigError(
                    code="DOCUMENT_BINDING_INVALID",
                    message=f"Invalid document binding: '{raw}'. Expected '<collection>' or '<collection> by <param>'",
                    path=path,
                )
            ]
        return (collection, id_param), []

    collection = parts[0].strip()
    if not collection:
        return None, [
            ConfigError(
                code="DOCUMENT_BINDING_INVALID",
                message=f"Invalid document binding: '{raw}'. Expected '<collection>' or '<collection> by <param>'",
                path=path,
            )
        ]
    return (collection, None), []
