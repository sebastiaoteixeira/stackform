"""Foundational v0.3 spec-version gate.

v0.3 is a superset of v0.2. These tests pin the scaffold behavior: a v0.2-shaped
spec at version 0.3 produces the same IR, dispatch routes to V03Transformer, and
the schema accepts the new v0.3 constructs syntactically.
"""
import json
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from yaml_api_generator.parsers.yaml_parser import (
    SCHEMA_REGISTRY,
    ConfigErrors,
    load_and_generate_ir,
)
from yaml_api_generator.parsers.transformers.registry import _TRANSFORMERS
from yaml_api_generator.parsers.transformers.v02 import V02Transformer
from yaml_api_generator.parsers.transformers.v03 import V03Transformer

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "yaml_api_generator" / "parsers" / "schemas" / "yaml-spec-v0.3.schema.json"
)

_V02_SHAPED = """
    version: "{version}"
    api:
      basePath: /api
      version: v1
    mongo:
      uri: mongodb://localhost:27017
      database: testdb
    entities:
      post:
        fields:
          id: {{ type: id }}
          title: {{ type: string }}
    repositories:
      posts:
        entity: post
    services:
      posts:
        repository: posts
    controllers:
      posts:
        service: posts
        base_path: /posts
        access: public
"""


def _ir(yaml_str: str, tmp_path, name: str):
    path = tmp_path / name
    path.write_text(textwrap.dedent(yaml_str))
    return load_and_generate_ir(str(path)).ir


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def test_v03_spec_produces_same_ir_as_v02_except_version(tmp_path):
    ir_02 = _ir(_V02_SHAPED.format(version="0.2"), tmp_path, "v02.yaml")
    ir_03 = _ir(_V02_SHAPED.format(version="0.3"), tmp_path, "v03.yaml")
    assert ir_02.version == "0.2"
    assert ir_03.version == "0.3"
    assert replace(ir_03, version="0.2") == ir_02


def test_v03_routes_to_v03_transformer():
    assert _TRANSFORMERS["0.3"] is V03Transformer
    assert issubclass(V03Transformer, V02Transformer)


def test_unsupported_version_still_raises(tmp_path):
    with pytest.raises(ConfigErrors) as exc_info:
        _ir(_V02_SHAPED.format(version="9.9"), tmp_path, "bad.yaml")
    assert any(e.code == "UNSUPPORTED_VERSION" for e in exc_info.value.errors)


def test_schema_accepts_new_v03_constructs():
    spec = {
        "version": "0.3",
        "api": {"basePath": "/api", "version": "v1"},
        "entities": {
            "post": {
                "fields": {
                    "id": {"type": "id"},
                    "title": {"type": "string"},
                    "ownerId": {"type": "string"},
                }
            }
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {
            "posts": {"repository": "posts", "input": ["orgId"], "with": {"orgId": "$orgId"}}
        },
        "controllers": {
            "posts": {
                "service": "posts",
                "base_path": "/posts",
                "access": [
                    {
                        "given": {"post": "ownerId = $userId and orgId = $orgId"},
                        "bind": {"userId": "$userId"},
                    },
                    {"given": {"post": "$currentUser"}},
                ],
            }
        },
    }
    errors = list(Draft202012Validator(_schema(), registry=SCHEMA_REGISTRY).iter_errors(spec))
    assert errors == []
