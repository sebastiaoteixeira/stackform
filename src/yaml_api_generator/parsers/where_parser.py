"""Tokenizer and recursive-descent parser for the v0.3 ``where`` binding form.

    binding  := collection 'where' conjunct ('and' conjunct)*
    conjunct := field '=' rhs
    rhs      := $symbol | 'string' | "string" | number | true | false

This parser is the authority on the grammar. ``=`` and ``and`` are active; the
comparison operators ``!=``, ``<``, ``<=``, ``>``, ``>=`` and ``in`` are
recognised but rejected with ``WHERE_OPERATOR_UNSUPPORTED`` until a later v0.3
release implements them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum, auto
from typing import NamedTuple

from yaml_api_generator.ir import IRLiteralRef, IRSymbolRef, IRWhereConjunct, WhereRhs
from .yaml_parser import ConfigError

WHERE_BINDING_INVALID = "WHERE_BINDING_INVALID"
WHERE_OPERATOR_UNSUPPORTED = "WHERE_OPERATOR_UNSUPPORTED"
WHERE_RHS_INVALID = "WHERE_RHS_INVALID"

GRAMMAR = "<collection> where <field> = <rhs> [and <field> = <rhs>]*"
ACTIVE_OPERATOR = "="


class TokenKind(Enum):
    WHERE = auto()
    AND = auto()
    OPERATOR = auto()
    SYMBOL = auto()
    STRING = auto()
    NUMBER = auto()
    BOOLEAN = auto()
    IDENTIFIER = auto()
    UNKNOWN = auto()
    END = auto()


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    lexeme: str
    position: int

    @property
    def column(self) -> int:
        return self.position + 1

    def describe(self) -> str:
        return "end of binding" if self.kind is TokenKind.END else repr(self.lexeme)


_KEYWORDS = {
    "where": TokenKind.WHERE,
    "and": TokenKind.AND,
    "in": TokenKind.OPERATOR,
    "true": TokenKind.BOOLEAN,
    "false": TokenKind.BOOLEAN,
}

_TOKEN = re.compile(
    r"""
      (?P<space>\s+)
    | (?P<symbol>\$[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)
    | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
    | (?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
    | (?P<word>[A-Za-z_]\w*)
    | (?P<operator>!=|<=|>=|[=<>])
    | (?P<unknown>['"].*|.)
    """,
    re.VERBOSE,
)


def tokenize(raw: str) -> Iterator[Token]:
    for match in _TOKEN.finditer(raw):
        group, lexeme = match.lastgroup, match.group()
        if group == "word":
            yield Token(_KEYWORDS.get(lexeme, TokenKind.IDENTIFIER), lexeme, match.start())
        elif group != "space":
            yield Token(TokenKind[group.upper()], lexeme, match.start())
    yield Token(TokenKind.END, "", len(raw))


def is_where_binding(raw: str) -> bool:
    return any(token.kind is TokenKind.WHERE for token in tokenize(raw))


class WhereBinding(NamedTuple):
    collection: str
    conjuncts: tuple[IRWhereConjunct, ...]

    @property
    def symbols(self) -> frozenset[str]:
        return frozenset(
            conjunct.rhs.root
            for conjunct in self.conjuncts
            if isinstance(conjunct.rhs, IRSymbolRef)
        )


_ESCAPE = re.compile(r"\\(.)")
_INTEGER = re.compile(r"[+-]?\d+")


def _symbol(lexeme: str) -> IRSymbolRef:
    root, *path = lexeme[1:].split(".")
    return IRSymbolRef(root=root, path=tuple(path))


def _string(lexeme: str) -> IRLiteralRef:
    return IRLiteralRef(value=_ESCAPE.sub(r"\1", lexeme[1:-1]))


def _number(lexeme: str) -> IRLiteralRef:
    return IRLiteralRef(value=int(lexeme) if _INTEGER.fullmatch(lexeme) else float(lexeme))


def _boolean(lexeme: str) -> IRLiteralRef:
    return IRLiteralRef(value=lexeme == "true")


_RHS: dict[TokenKind, Callable[[str], WhereRhs]] = {
    TokenKind.SYMBOL: _symbol,
    TokenKind.STRING: _string,
    TokenKind.NUMBER: _number,
    TokenKind.BOOLEAN: _boolean,
}


class _Parser:
    def __init__(self, raw: str, path: str) -> None:
        self._raw = raw
        self._path = path
        self._tokens = list(tokenize(raw))
        self._index = 0

    @property
    def _current(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._current
        self._index += 1
        return token

    def _expect(self, kind: TokenKind, expected: str) -> Token:
        if self._current.kind is not kind:
            raise self._invalid(expected)
        return self._advance()

    def parse(self) -> WhereBinding:
        collection = self._expect(TokenKind.IDENTIFIER, "a collection name").lexeme
        self._expect(TokenKind.WHERE, "'where'")
        conjuncts = [self._conjunct()]
        while self._current.kind is TokenKind.AND:
            self._advance()
            conjuncts.append(self._conjunct())
        if self._current.kind is not TokenKind.END:
            raise self._invalid("'and' or end of binding")
        return WhereBinding(collection, tuple(conjuncts))

    def parse_rhs(self) -> WhereRhs:
        rhs = self._rhs()
        if self._current.kind is not TokenKind.END:
            raise self._invalid("end of value")
        return rhs

    def _conjunct(self) -> IRWhereConjunct:
        field = self._expect(TokenKind.IDENTIFIER, "a field name").lexeme
        operator = self._expect(TokenKind.OPERATOR, f"'{ACTIVE_OPERATOR}'")
        if operator.lexeme != ACTIVE_OPERATOR:
            raise ConfigError(
                code=WHERE_OPERATOR_UNSUPPORTED,
                message=(
                    f"where operator '{operator.lexeme}' is reserved but not implemented; "
                    f"only '{ACTIVE_OPERATOR}' is active in v0.3"
                ),
                path=self._path,
                hint=f"Compare with '{ACTIVE_OPERATOR}'",
            )
        return IRWhereConjunct(field=field, rhs=self._rhs())

    def _rhs(self) -> WhereRhs:
        build = _RHS.get(self._current.kind)
        if build is None:
            raise ConfigError(
                code=WHERE_RHS_INVALID,
                message=(
                    f"Invalid right-hand side {self._current.describe()} at column "
                    f"{self._current.column} in where binding '{self._raw}'"
                ),
                path=self._path,
                hint="Use a $symbol, a quoted string, a number, or true/false",
            )
        return build(self._advance().lexeme)

    def _invalid(self, expected: str) -> ConfigError:
        return ConfigError(
            code=WHERE_BINDING_INVALID,
            message=(
                f"Invalid where binding: '{self._raw}'. Expected {expected} at column "
                f"{self._current.column}, found {self._current.describe()}"
            ),
            path=self._path,
            hint=f"Expected '{GRAMMAR}'",
        )


def parse_where_binding(
    raw: str, path: str
) -> tuple[WhereBinding | None, list[ConfigError]]:
    try:
        return _Parser(raw, path).parse(), []
    except ConfigError as error:
        return None, [error]


def parse_rhs_value(raw: str, path: str) -> tuple[WhereRhs | None, list[ConfigError]]:
    try:
        return _Parser(raw, path).parse_rhs(), []
    except ConfigError as error:
        return None, [error]
