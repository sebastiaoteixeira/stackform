"""Soft deletion and time to live: what the grammar accepts and the IR it produces."""

import copy

import pytest
import yaml

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.runtime.lifecycle import Expiry, Lifecycle

FIELDS = {"id": {"type": "id"}, "title": {"type": "string"}, "createdAt": {"type": "datetime"}}
FIND = {"query": {"command": "find", "filter": {}}}


def _spec(version: str, repository: dict) -> dict:
    return {
        "version": version,
        "api": {"basePath": "/api"},
        "entities": {"post": {"fields": FIELDS}},
        "repositories": {"posts": {"entity": "post", **repository}},
        "services": {"posts": {"repository": "posts"}},
        "controllers": {
            "posts": {"service": "posts", "base_path": "/posts", "access": [{"then": "allow"}]}
        },
    }


def _load(tmp_path, spec: dict):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec))
    return load_and_generate_ir(str(path)).ir


def _errors(tmp_path, spec: dict) -> list:
    with pytest.raises(ConfigErrors) as exc_info:
        _load(tmp_path, spec)
    return exc_info.value.errors


VERSIONS = ("0.2", "0.3")

REJECTED = {
    "include-deleted-without-lifecycle": {"operations": {"all": {**FIND, "includeDeleted": True}}},
    "include-deleted-on-handler": {
        "softDelete": "deletedAt",
        "operations": {"all": {"handler": "helpers.run", "includeDeleted": True}},
    },
    "sql-without-include-deleted": {
        "softDelete": "deletedAt",
        "operations": {"raw": {"query": {"sql": "SELECT * FROM posts"}}},
    },
    "estimated-count-without-include-deleted": {
        "ttl": {"field": "createdAt", "seconds": 60},
        "operations": {"count": {"query": {"command": "estimatedDocumentCount"}}},
    },
    "bulk-write-include-deleted-false": {
        "softDelete": "deletedAt",
        "operations": {"bulk": {"query": {"command": "bulkWrite"}, "includeDeleted": False}},
    },
    "ttl-zero-seconds": {"ttl": {"field": "createdAt", "seconds": 0}},
    "ttl-without-field": {"ttl": {"seconds": 60}},
    "ttl-unknown-key": {"ttl": {"field": "createdAt", "seconds": 60, "index": True}},
    "soft-delete-boolean": {"softDelete": True},
}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("repository", REJECTED.values(), ids=list(REJECTED))
def test_schema_rejects_misused_lifecycle_keys(tmp_path, version, repository):
    errors = _errors(tmp_path, _spec(version, repository))
    assert {error.code for error in errors} == {"SCHEMA_VALIDATION_ERROR"}


@pytest.mark.parametrize("version", VERSIONS)
def test_lifecycle_requires_a_concrete_repository(tmp_path, version):
    spec = _spec(version, {})
    spec["repositories"]["base"] = {"abstract": True, "softDelete": "deletedAt"}
    errors = _errors(tmp_path, spec)
    assert {error.code for error in errors} == {"SCHEMA_VALIDATION_ERROR"}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize(
    ("repository", "code", "path"),
    [
        ({"softDelete": "title"}, "LIFECYCLE_FIELD_NOT_DATETIME", "softDelete"),
        ({"ttl": {"field": "title", "seconds": 60}}, "LIFECYCLE_FIELD_NOT_DATETIME", "ttl.field"),
        ({"ttl": {"field": "expiresAt", "seconds": 60}}, "LIFECYCLE_FIELD_NOT_FOUND", "ttl.field"),
    ],
)
def test_lifecycle_timestamps_must_be_datetime_fields(tmp_path, version, repository, code, path):
    errors = _errors(tmp_path, _spec(version, repository))
    assert [(error.code, error.path) for error in errors] == [(code, f"repositories.posts.{path}")]


@pytest.mark.parametrize("version", VERSIONS)
def test_soft_delete_adds_a_readonly_timestamp_and_binds_the_lifecycle(tmp_path, version):
    spec = _spec(
        version,
        {
            "softDelete": "deletedAt",
            "ttl": {"field": "createdAt", "seconds": 3600},
            "operations": {"all": {**FIND, "includeDeleted": True}, "visible": copy.deepcopy(FIND)},
        },
    )
    ir = _load(tmp_path, spec)
    collection = ir.collections["posts"]
    assert collection.fields["deletedAt"] == {"type": "datetime", "readonly": True}
    assert collection.lifecycle == Lifecycle(removal="deletedAt", expiry=Expiry("createdAt", 3600))
    operations = ir.repositories["posts"].operations
    assert operations["all"].query.get("includeDeleted") and "includeDeleted" not in operations["visible"].query


@pytest.mark.parametrize("version", VERSIONS)
def test_declared_soft_delete_field_is_kept(tmp_path, version):
    spec = _spec(version, {"softDelete": "removedAt"})
    spec["entities"]["post"]["fields"]["removedAt"] = {"type": "datetime"}
    assert _load(tmp_path, spec).collections["posts"].fields["removedAt"] == {"type": "datetime"}


def test_v01_soft_delete_uses_deleted_at(tmp_path):
    spec = {
        "version": "0.1",
        "collections": {"posts": {"softDelete": True, "fields": {"id": {"type": "id"}}}},
    }
    collection = _load(tmp_path, spec).collections["posts"]
    assert collection.lifecycle == Lifecycle(removal="deletedAt")
    assert collection.fields["deletedAt"] == {"type": "datetime", "readonly": True}


def test_v01_collection_without_soft_delete_keeps_rows_on_delete(tmp_path):
    spec = {"version": "0.1", "collections": {"posts": {"fields": {"id": {"type": "id"}}}}}
    assert _load(tmp_path, spec).collections["posts"].lifecycle == Lifecycle()
