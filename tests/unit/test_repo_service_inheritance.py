"""Tests for repository/service inheritance (abstract/extends).

An abstract repository that declares ``operations`` is generated as a real
base class; concrete repositories that ``extends`` it become Python subclasses
of that generated class. Nothing is hand-written and nothing is flattened.
"""

import textwrap

import pytest

from yaml_api_generator.parsers.desugar import desugar_v02
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.context_builder import build_context
from tests.conftest import VALID_DIR


def _base_config() -> dict:
    return {
        "api": {
            "basePath": "/api",
            "version": "v1",
            "operations": {
                "defaults": {"list": True, "get": True, "create": True, "update": True, "replace": False, "delete": True},
            },
        },
        "mongo": {"uri": "mongodb://localhost:27017", "database": "testdb"},
        "entities": {"post": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}}},
        "repositories": {"posts": {"entity": "post"}},
        "services": {"posts": {"repository": "posts"}},
        "controllers": {"posts": {"service": "posts", "base_path": "/posts", "access": "public"}},
    }


def _parse(yaml_str: str, tmp_path):
    path = tmp_path / "test.yaml"
    path.write_text(textwrap.dedent(yaml_str))
    return load_and_generate_ir(str(path)).ir


# ---------------------------------------------------------------------------
# Desugar validation
# ---------------------------------------------------------------------------


def test_repo_extends_nonexistent_raises():
    config = _base_config()
    config["repositories"]["posts"]["extends"] = "ghost"
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "REPOSITORY_EXTENDS_NOT_FOUND" for e in exc_info.value.errors)


def test_repo_extends_non_abstract_raises():
    config = _base_config()
    config["repositories"]["other"] = {"entity": "post"}
    config["repositories"]["posts"]["extends"] = "other"
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "REPOSITORY_EXTENDS_NOT_ABSTRACT" for e in exc_info.value.errors)


def test_repo_circular_extends_raises():
    config = _base_config()
    config["repositories"]["a"] = {"abstract": True, "extends": "b", "operations": {}}
    config["repositories"]["b"] = {"abstract": True, "extends": "a", "operations": {}}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "REPOSITORY_CIRCULAR_EXTENDS" for e in exc_info.value.errors)


def test_service_extends_nonexistent_raises():
    config = _base_config()
    config["services"]["posts"]["extends"] = "ghost"
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "SERVICE_EXTENDS_NOT_FOUND" for e in exc_info.value.errors)


def test_abstract_repo_bound_to_controller_raises():
    config = _base_config()
    config["repositories"]["base"] = {"abstract": True, "operations": {"countAll": {"query": {"command": "estimatedDocumentCount"}}}}
    config["controllers"]["posts"]["repository"] = "base"
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ABSTRACT_REPOSITORY_BOUND" for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# IR: abstract repos kept, concrete repos carry the inherited base
# ---------------------------------------------------------------------------


_FIXTURE = """
    version: "0.2"
    api:
      basePath: /api
      version: v1
    mongo:
      uri: mongodb://localhost:27017
      database: testdb
    entities:
      post:
        fields:
          id: { type: id }
          title: { type: string }
    repositories:
      countable:
        abstract: true
        operations:
          countAll: { query: { command: estimatedDocumentCount } }
      posts:
        entity: post
        extends: countable
    services:
      posts:
        repository: posts
    controllers:
      posts:
        service: posts
        base_path: /posts
        access: public
"""


def test_abstract_repo_with_operations_kept_in_ir(tmp_path):
    ir = _parse(_FIXTURE, tmp_path)
    assert "countable" in ir.repositories
    assert ir.repositories["countable"].abstract is True
    assert "countAll" in ir.repositories["countable"].operations


def test_concrete_repo_carries_inherited_base(tmp_path):
    ir = _parse(_FIXTURE, tmp_path)
    assert ir.repositories["posts"].inherits == "countable"
    assert ir.repositories["posts"].abstract is False


def test_empty_abstract_repo_removed_from_ir():
    config = _base_config()
    config["repositories"]["marker"] = {"abstract": True}
    config = desugar_v02(config)
    assert "marker" not in config["repositories"]


# ---------------------------------------------------------------------------
# FastAPI code generation: visible inheritance of a generated base class
# ---------------------------------------------------------------------------


def _generate_fixture(tmp_path):
    result = load_and_generate_ir(str(VALID_DIR / "repo-service-inheritance.yaml"))
    FastAPIGenerator().generate(build_context(result.ir), tmp_path)


def test_abstract_repo_generates_base_class(tmp_path):
    _generate_fixture(tmp_path)
    base_src = (tmp_path / "repositories" / "countable.py").read_text()
    assert "class CountableRepository" in base_src
    assert "async def countAll" in base_src
    assert "COLLECTION" not in base_src  # abstract: not bound to a collection


def test_concrete_repo_inherits_generated_base(tmp_path):
    _generate_fixture(tmp_path)
    repo_src = (tmp_path / "repositories" / "posts.py").read_text()
    assert "from .countable import CountableRepository" in repo_src
    assert "CountableRepository, RepositoryBase" in repo_src
    assert "async def countAll" not in repo_src  # inherited, not redefined


def test_abstract_service_bound_to_controller_raises():
    config = _base_config()
    config["services"]["base"] = {"abstract": True, "operations": {"delete": False}}
    config["controllers"]["posts"]["service"] = "base"
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ABSTRACT_SERVICE_BOUND" for e in exc_info.value.errors)


def test_repository_extends_merges_inherited_and_own_operations():
    config = _base_config()
    config["repositories"]["base"] = {"abstract": True, "operations": {"countAll": {"query": {"command": "estimatedDocumentCount"}}}}
    config["repositories"]["posts"] |= {"extends": "base", "operations": {"byTitle": {"query": {"command": "find"}}}}
    operations = desugar_v02(config)["repositories"]["posts"]["operations"]
    assert set(operations) == {"countAll", "byTitle"}


def test_service_extends_merges_inherited_and_own_operations():
    config = _base_config()
    config["repositories"]["posts"]["operations"] = {"countAll": {"query": {"command": "estimatedDocumentCount"}}}
    config["services"]["base"] = {"abstract": True, "operations": {"delete": False, "countAll": True}}
    config["services"]["posts"] |= {"extends": "base", "operations": {"update": False}}
    config["controllers"]["posts"]["operations"] = {"countAll": {"method": "GET", "path": "/count"}}
    services = desugar_v02(config)["services"]
    assert {"countAll-posts", "list-posts", "get-posts", "create-posts"} <= set(services)
    assert not {"delete-posts", "update-posts"} & set(services)
    assert services["countAll-posts"]["_inherits"] == "base"


_SERVICE_FIXTURE = _FIXTURE.replace(
    """    services:
      posts:
        repository: posts
""",
    """    services:
      auditable:
        abstract: true
        operations:
          countAll: true
          summary: { handler: hooks.summary }
      posts:
        repository: posts
        extends: auditable
""",
).replace("        access: public\n", "        access: public\n        operations:\n          countAll: { method: GET, path: /count }\n          summary: { method: GET, path: /summary }\n")


def test_abstract_service_is_a_base_in_ir(tmp_path):
    ir = _parse(_SERVICE_FIXTURE, tmp_path)
    assert ir.service_bases["auditable"].operations == {"countAll": None, "summary": "hooks.summary"}
    assert "auditable" not in ir.services
    assert ir.services["countAll-posts"].inherits == "auditable"


def test_abstract_service_generates_a_base_class_its_services_extend(tmp_path):
    FastAPIGenerator().generate(build_context(_parse(_SERVICE_FIXTURE, tmp_path)), tmp_path / "out")
    base_src = (tmp_path / "out" / "services" / "auditable.py").read_text()
    service_src = (tmp_path / "out" / "services" / "posts.py").read_text()
    assert "class AuditableService(ServiceBase)" in base_src
    assert "async def countAll" in base_src and "async def summary" in base_src
    assert "from services.auditable import AuditableService" in service_src
    assert "async def countAll" not in service_src
