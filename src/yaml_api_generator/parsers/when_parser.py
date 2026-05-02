from __future__ import annotations

import re
from typing import Any

from ..ir import (
    And,
    Equals,
    FieldRef,
    In,
    Not,
    NotEquals,
    NotIn,
    Or,
    StringLiteral,
    WhenExpr,
)
from .yaml_parser import ConfigError


# Tokenizer: multi-word operators must be listed before their prefixes
_TOKEN_PATTERNS = [
    ("NOT_EQUALS", r"not\s+equals"),
    ("NOT_IN",     r"not\s+in"),
    ("EQUALS",     r"equals"),
    ("IN",         r"in"),
    ("AND",        r"and"),
    ("OR",         r"or"),
    ("NOT",        r"not"),
    ("LBRACKET",   r"\["),
    ("RBRACKET",   r"\]"),
    ("COMMA",      r","),
    ("STRING",     r"'[^']*'"),
    ("FIELDREF",   r"(?:principal|document)(?:\.\w+)+"),
    ("WORD",       r"\w+"),
    ("WS",         r"\s+"),
]

_MASTER_RE = re.compile(
    "|".join(f"(?P<{name}>{pat})" for name, pat in _TOKEN_PATTERNS),
    re.IGNORECASE,
)


def _tokenize(raw: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for m in _MASTER_RE.finditer(raw):
        kind = m.lastgroup
        if kind == "WS":
            continue
        assert kind is not None
        tokens.append((kind, m.group()))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], path: str) -> None:
        self._tokens = tokens
        self._pos = 0
        self._path = path
        self.errors: list[ConfigError] = []

    def _peek(self) -> tuple[str, str] | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _consume(self) -> tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def parse(self) -> WhenExpr | None:
        expr = self._parse_or()
        if self._peek() is not None and not self.errors:
            tok = self._peek()
            self.errors.append(ConfigError(
                code="WHEN_EXPR_INVALID",
                message=f"Unexpected token '{tok[1] if tok else ''}' in when expression",
                path=self._path,
            ))
            return None
        return expr

    def _parse_or(self) -> WhenExpr | None:
        left = self._parse_and()
        if left is None:
            return None
        while self._peek() and self._peek()[0] == "OR":
            self._consume()
            right = self._parse_and()
            if right is None:
                return None
            left = Or(left=left, right=right)
        return left

    def _parse_and(self) -> WhenExpr | None:
        left = self._parse_not()
        if left is None:
            return None
        while self._peek() and self._peek()[0] == "AND":
            self._consume()
            right = self._parse_not()
            if right is None:
                return None
            left = And(left=left, right=right)
        return left

    def _parse_not(self) -> WhenExpr | None:
        if self._peek() and self._peek()[0] == "NOT":
            self._consume()
            operand = self._parse_not()
            if operand is None:
                return None
            return Not(operand=operand)
        return self._parse_comparison()

    def _parse_comparison(self) -> WhenExpr | None:
        lhs = self._parse_operand()
        if lhs is None:
            return None

        tok = self._peek()
        if tok is None:
            return lhs

        if tok[0] == "EQUALS":
            self._consume()
            rhs = self._parse_operand()
            if rhs is None:
                return None
            return Equals(left=lhs, right=rhs)

        if tok[0] == "NOT_EQUALS":
            self._consume()
            rhs = self._parse_operand()
            if rhs is None:
                return None
            return NotEquals(left=lhs, right=rhs)

        if tok[0] == "IN":
            self._consume()
            values = self._parse_list()
            if values is None:
                return None
            return In(left=lhs, values=tuple(values))

        if tok[0] == "NOT_IN":
            self._consume()
            values = self._parse_list()
            if values is None:
                return None
            return NotIn(left=lhs, values=tuple(values))

        return lhs

    def _parse_list(self) -> list[Any] | None:
        tok = self._peek()
        if tok is None or tok[0] != "LBRACKET":
            self.errors.append(ConfigError(
                code="WHEN_LIST_INVALID",
                message="Expected '[' for list literal in 'in'/'not in' expression",
                path=self._path,
            ))
            return None
        self._consume()

        values: list[Any] = []
        while True:
            tok = self._peek()
            if tok is None:
                self.errors.append(ConfigError(
                    code="WHEN_LIST_INVALID",
                    message="Unterminated list literal",
                    path=self._path,
                ))
                return None
            if tok[0] == "RBRACKET":
                self._consume()
                break
            if tok[0] == "STRING":
                self._consume()
                values.append(tok[1][1:-1])
            elif tok[0] == "WORD":
                self._consume()
                values.append(tok[1])
            elif tok[0] == "COMMA":
                self._consume()
            else:
                self.errors.append(ConfigError(
                    code="WHEN_LIST_INVALID",
                    message=f"Unexpected token '{tok[1]}' inside list literal",
                    path=self._path,
                ))
                return None

        return values

    def _parse_operand(self) -> WhenExpr | None:
        tok = self._peek()
        if tok is None:
            self.errors.append(ConfigError(
                code="WHEN_OPERAND_MISSING",
                message="Expected an operand (field reference or string literal)",
                path=self._path,
            ))
            return None

        if tok[0] == "FIELDREF":
            self._consume()
            parts = tok[1].split(".")
            return FieldRef(root=parts[0], path=tuple(parts[1:]))

        if tok[0] == "STRING":
            self._consume()
            return StringLiteral(value=tok[1][1:-1])

        self.errors.append(ConfigError(
            code="WHEN_OPERAND_INVALID",
            message=(
                f"Invalid operand: '{tok[1]}'. "
                "Expected a field reference (principal.*/document.*) or a string literal ('...')"
            ),
            path=self._path,
        ))
        return None


def parse_when_expr(raw: str, path: str) -> tuple[WhenExpr | None, list[ConfigError]]:
    tokens = _tokenize(raw.strip())
    parser = _Parser(tokens, path)
    expr = parser.parse()
    if parser.errors:
        return None, parser.errors
    if expr is None:
        return None, [ConfigError(
            code="WHEN_EXPR_INVALID",
            message=f"Empty or invalid when expression: '{raw}'",
            path=path,
        )]
    return expr, []


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
