"""Tests for repository and service layer inheritance (abstract/extends/base)."""

import textwrap

import pytest

from yaml_api_generator.parsers.desugar import desugar_v02
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.context_builder import build_context
from tests.conftest import VALID_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# Desugar: repository inheritance validation
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
    config["repositories"]["a"] = {"abstract": True, "base": "x.A", "extends": "b"}
    config["repositories"]["b"] = {"abstract": True, "base": "x.B", "extends": "a"}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "REPOSITORY_CIRCULAR_EXTENDS" for e in exc_info.value.errors)



def test_abstract_repo_not_in_ir(tmp_path):
    ir = _parse("""
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
          auditedRepo:
            abstract: true
            base: app.bases.AuditedRepository
          posts:
            entity: post
            extends: auditedRepo
        services:
          posts:
            repository: posts
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    assert "auditedRepo" not in ir.repositories
    assert "posts" in ir.repositories


def test_repo_ir_carries_base_classes(tmp_path):
    ir = _parse("""
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
          auditedRepo:
            abstract: true
            base: app.bases.AuditedRepository
          posts:
            entity: post
            extends: auditedRepo
        services:
          posts:
            repository: posts
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    assert ir.repositories["posts"].base_classes == ("app.bases.AuditedRepository",)


# ---------------------------------------------------------------------------
# Desugar: service inheritance validation
# ---------------------------------------------------------------------------


def test_service_extends_nonexistent_raises():
    config = _base_config()
    config["services"]["posts"]["extends"] = "ghost"
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "SERVICE_EXTENDS_NOT_FOUND" for e in exc_info.value.errors)


def test_service_extends_non_abstract_raises():
    config = _base_config()
    config["services"]["other"] = {"repository": "posts"}
    config["services"]["posts"]["extends"] = "other"
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "SERVICE_EXTENDS_NOT_ABSTRACT" for e in exc_info.value.errors)


def test_service_circular_extends_raises():
    config = _base_config()
    config["services"]["a"] = {"abstract": True, "base": "x.A", "extends": "b"}
    config["services"]["b"] = {"abstract": True, "base": "x.B", "extends": "a"}
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "SERVICE_CIRCULAR_EXTENDS" for e in exc_info.value.errors)


def test_abstract_service_bound_to_controller_raises():
    config = _base_config()
    config["services"]["auditedSvc"] = {"abstract": True, "base": "app.bases.AuditedService"}
    config["controllers"]["posts"]["service"] = "auditedSvc"
    with pytest.raises(ConfigErrors) as exc_info:
        desugar_v02(config)
    assert any(e.code == "DESUGAR_ABSTRACT_SERVICE_BOUND" for e in exc_info.value.errors)


def test_abstract_service_not_in_ir(tmp_path):
    ir = _parse("""
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
          posts:
            entity: post
        services:
          auditedSvc:
            abstract: true
            base: app.bases.AuditedService
          posts:
            repository: posts
            extends: auditedSvc
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    assert not any(svc.name == "auditedSvc" for svc in ir.services.values())


# ---------------------------------------------------------------------------
# FastAPI code generation
# ---------------------------------------------------------------------------


def test_fastapi_repo_emits_user_base_import_and_inheritance(tmp_path):
    result = load_and_generate_ir(str(VALID_DIR / "repo-service-inheritance.yaml"))
    ctx = build_context(result.ir)
    FastAPIGenerator().generate(ctx, tmp_path)
    repo_src = (tmp_path / "repositories" / "posts.py").read_text()
    assert "from app.bases import AuditedRepository" in repo_src
    assert "AuditedRepository, RepositoryBase" in repo_src


def test_fastapi_service_emits_user_base_import_and_inheritance(tmp_path):
    result = load_and_generate_ir(str(VALID_DIR / "repo-service-inheritance.yaml"))
    ctx = build_context(result.ir)
    FastAPIGenerator().generate(ctx, tmp_path)
    svc_src = (tmp_path / "services" / "posts.py").read_text()
    assert "from app.bases import AuditedService" in svc_src
    assert "AuditedService, ServiceBase" in svc_src


def test_fastapi_abstract_repo_produces_no_file(tmp_path):
    result = load_and_generate_ir(str(VALID_DIR / "repo-service-inheritance.yaml"))
    ctx = build_context(result.ir)
    FastAPIGenerator().generate(ctx, tmp_path)
    assert not (tmp_path / "repositories" / "auditedRepo.py").exists()
    assert not (tmp_path / "repositories" / "audited_repo.py").exists()


def test_service_ir_carries_base_classes(tmp_path):
    ir = _parse("""
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
          posts:
            entity: post
        services:
          auditedSvc:
            abstract: true
            base: app.bases.AuditedService
          posts:
            repository: posts
            extends: auditedSvc
        controllers:
          posts:
            service: posts
            base_path: /posts
            access: public
    """, tmp_path)
    # Flat services (list-posts, get-posts, ...) should carry base_classes
    posts_services = [svc for svc in ir.services.values() if svc.repository == "posts"]
    assert posts_services, "No expanded services for posts"
    assert all(svc.base_classes == ("app.bases.AuditedService",) for svc in posts_services)
