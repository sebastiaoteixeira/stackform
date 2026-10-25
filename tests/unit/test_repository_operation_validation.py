"""Routes must reach an operation their repository provides or a handler."""
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
    "api": {"basePath": "/api"},
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


def _errors(tmp_path, spec):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec))
    with pytest.raises(ConfigErrors) as excinfo:
        load_and_generate_ir(str(path))
    return excinfo.value.errors


def test_undeclared_repository_operation_is_rejected(tmp_path):
    [error] = _errors(tmp_path, _SPEC)
    assert error.code == "REPOSITORY_OPERATION_UNDECLARED"
    assert "recent" in error.message


def test_operation_excluded_from_crud_is_rejected(tmp_path):
    spec = copy.deepcopy(_SPEC)
    spec["repositories"]["posts"]["crud"] = ["list", "get"]
    spec["controllers"]["posts"]["routes"] = {
        "delete": {"service": "posts", "method": "DELETE", "path": "/{id}"}
    }
    [error] = _errors(tmp_path, spec)
    assert error.code == "REPOSITORY_OPERATION_UNDECLARED"
    assert "delete" in error.message


def test_pagination_outside_a_list_is_rejected(tmp_path):
    spec = copy.deepcopy(_SPEC)
    spec["repositories"]["posts"]["operations"] = _OPERATION
    spec["controllers"]["posts"]["routes"]["recent"]["pagination"] = {
        "strategy": "offset", "size": {"default": 10, "max": 50}
    }
    [error] = _errors(tmp_path, spec)
    assert error.code == "PAGINATION_UNSUPPORTED"


@pytest.mark.parametrize("generator", _GENERATORS)
def test_declared_repository_operation_emits_its_query(tmp_path, generator):
    out = tmp_path / "out"
    generator().generate(_context(tmp_path, declare_operation=True), out)

    sources = [path.read_text() for path in out.rglob("*.py")]
    assert any("'state': 'published'" in source for source in sources)


def test_query_targeting_an_unknown_collection_is_rejected(tmp_path):
    spec = copy.deepcopy(_SPEC)
    spec["repositories"]["posts"]["operations"] = {
        "recent": {"query": {"command": "find", "collection": "postz", "filter": {}}}
    }
    [error] = _errors(tmp_path, spec)
    assert (error.code, error.path) == (
        "QUERY_COLLECTION_NOT_FOUND", "repositories.posts.operations.recent.query.collection"
    )


def test_query_targeting_a_declared_collection_is_accepted(tmp_path):
    spec = copy.deepcopy(_SPEC)
    spec["repositories"]["posts"]["operations"] = {
        "recent": {"query": {"command": "find", "collection": "posts", "filter": {}}}
    }
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec))
    load_and_generate_ir(str(path))
