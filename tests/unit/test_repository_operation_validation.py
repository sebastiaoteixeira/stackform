"""Routes dispatching to an undeclared repository operation are rejected.

A route whose operation is neither built in nor a custom handler is emitted as a
call into its repository, filtered by the query that operation declares. When no
repository declares it there is no query to emit, and the backends used to
render the Jinja undefined sentinel into the generated source as the bare name
``Undefined`` -- syntactically valid Python that byte-compiles, passes every
syntax-level check, and raises ``NameError`` only once the route is called.
"""
import copy

import pytest
import yaml

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


_GENERATORS = (FastAPIGenerator, DRFGenerator, RawASGIGenerator)

_SPEC = {
    "version": "0.3",
    "api": {"name": "undeclared-operation", "basePath": "/api"},
    "entities": {
        "post": {
            "fields": {
                "id": {"type": "id"},
                "title": {"type": "string", "required": True},
            }
        }
    },
    "repositories": {"posts": {"entity": "post"}},
    "services": {"posts": {"repository": "posts"}},
    "controllers": {
        "posts": {
            "base_path": "/posts",
            "routes": {
                "recent": {"service": "posts", "method": "GET", "path": "/recent"}
            },
        }
    },
}

_OPERATION = {
    "recent": {"query": {"command": "find", "filter": {"state": "published"}}}
}


def _context(tmp_path, *, declare_operation):
    spec = copy.deepcopy(_SPEC)
    if declare_operation:
        spec["repositories"]["posts"]["operations"] = _OPERATION
        spec["services"]["posts"]["operation"] = "recent"
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec))
    return build_context(load_and_generate_ir(str(path)).ir)


@pytest.mark.parametrize("generator", _GENERATORS)
def test_undeclared_repository_operation_is_rejected(tmp_path, generator):
    context = _context(tmp_path, declare_operation=False)

    with pytest.raises(ConfigErrors) as excinfo:
        generator().generate(context, tmp_path / "out")

    [error] = excinfo.value.errors
    assert error.code == "REPOSITORY_OPERATION_UNDECLARED"
    assert "recent" in error.message


@pytest.mark.parametrize("generator", _GENERATORS)
def test_declared_repository_operation_emits_its_query(tmp_path, generator):
    out = tmp_path / "out"
    generator().generate(_context(tmp_path, declare_operation=True), out)

    sources = [path.read_text() for path in out.rglob("*.py")]
    assert any("'state': 'published'" in source for source in sources)
