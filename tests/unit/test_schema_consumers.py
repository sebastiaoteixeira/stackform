"""Every key a spec schema accepts is read by some consumer: parser, generator or UI pack.

A key counts as consumed when it occurs as an identifier or a string literal in the
package's Python code, or anywhere in its Jinja templates. Docstrings and dict
display keys do not count: the latter write a key, as schema builders do, rather
than read one.
"""

import ast
import json
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[2] / "src" / "yaml_api_generator"
SCHEMAS = PACKAGE / "parsers" / "schemas"

# Accepted by the schema but read by no consumer yet.
UNENFORCED: dict[str, str] = {}

# Read by an external tool from a block the generator copies verbatim.
VERBATIM = {
    "dockerfile": "deploy.services.<name>.build, rendered into docker-compose",
}


def _schema_keys(node, location: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                for name, sub in value.items():
                    yield name, f"{location}.{name}"
                    yield from _schema_keys(sub, f"{location}.{name}")
            else:
                yield from _schema_keys(value, location)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_keys(item, location)


def _docstring_ids(tree: ast.Module) -> set[int]:
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, scopes)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }


def _written_key_ids(tree: ast.Module) -> set[int]:
    return {id(key) for node in ast.walk(tree) if isinstance(node, ast.Dict) for key in node.keys if key is not None}


def _python_words(source: str) -> Iterator[str]:
    tree = ast.parse(source)
    unread = _docstring_ids(tree) | _written_key_ids(tree)
    for node in ast.walk(tree):
        match node:
            case ast.Constant(value=str(text)) if id(node) not in unread:
                yield text
            case ast.Name(id=word) | ast.Attribute(attr=word) | ast.arg(arg=word) | ast.alias(name=word):
                yield word
            case ast.keyword(arg=str(word)) | ast.FunctionDef(name=word) | ast.ClassDef(name=word):
                yield word


@cache
def _corpus() -> str:
    return "\n".join(
        [
            *(word for path in PACKAGE.rglob("*.py") for word in _python_words(path.read_text())),
            *(path.read_text() for path in PACKAGE.rglob("*.jinja")),
        ]
    )


@cache
def _locations() -> dict[str, tuple[str, ...]]:
    found: dict[str, list[str]] = {}
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        for key, location in _schema_keys(json.loads(path.read_text())):
            found.setdefault(key, []).append(f"{path.name}{location}")
    return {key: tuple(locations) for key, locations in found.items()}


def _consumed(key: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", _corpus()) is not None


EXEMPT = UNENFORCED | VERBATIM


def test_every_schema_key_has_a_consumer():
    orphans = {
        key: locations[:3]
        for key, locations in _locations().items()
        if key not in EXEMPT and not _consumed(key)
    }
    assert orphans == {}


@pytest.mark.parametrize("key", sorted(EXEMPT))
def test_exempt_key_is_still_an_unconsumed_schema_key(key):
    assert key in _locations()
    assert key in VERBATIM or not _consumed(key)
