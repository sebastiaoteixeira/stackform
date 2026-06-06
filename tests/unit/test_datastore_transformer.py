"""Tests for v0.2 datastore registry parsing and per-repository binding."""
import textwrap

import pytest

from yaml_api_generator.ir import IRMongo, IRPostgres
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


def _parse(yaml_str: str, tmp_path):
    path = tmp_path / "test.yaml"
    path.write_text(textwrap.dedent(yaml_str))
    return load_and_generate_ir(str(path)).ir


_MULTI = """
    version: "0.2"
    api:
      basePath: /api
    datastores:
      main: { type: mongodb, default: true }
      warehouse: { type: postgres, dsn: "postgresql+asyncpg://localhost/wh" }
    entities:
      post: { fields: { id: { type: id }, title: { type: string } } }
      event: { fields: { id: { type: id }, kind: { type: string } } }
    repositories:
      posts: { entity: post }
      events: { entity: event, datastore: warehouse }
    services:
      posts: { repository: posts }
    controllers:
      posts:
        base_path: /posts
        routes: { list: { service: posts, method: GET, path: "" } }
"""


def test_no_datastores_block_synthesizes_default_from_mongo(tmp_path):
    ir = _parse(
        """
        version: "0.2"
        api: { basePath: /api }
        mongo: { uri: mongodb://localhost:27017, database: testdb }
        entities:
          post: { fields: { id: { type: id }, title: { type: string } } }
        repositories:
          posts: { entity: post }
        services:
          posts: { repository: posts }
        controllers:
          posts:
            base_path: /posts
            routes: { list: { service: posts, method: GET, path: "" } }
        """,
        tmp_path,
    )
    assert ir.default_datastore == "default"
    assert list(ir.datastores) == ["default"]
    assert isinstance(ir.datastores["default"], IRMongo)
    assert ir.datastores["default"].database == "testdb"
    assert ir.repositories["posts"].datastore == "default"
    assert ir.collections["posts"].datastore == "default"


def test_multi_datastore_binding(tmp_path):
    ir = _parse(_MULTI, tmp_path)
    assert ir.default_datastore == "main"
    assert isinstance(ir.datastores["main"], IRMongo)
    assert isinstance(ir.datastores["warehouse"], IRPostgres)
    assert ir.repositories["posts"].datastore == "main"
    assert ir.repositories["events"].datastore == "warehouse"
    assert ir.collections["events"].datastore == "warehouse"


def test_unknown_datastore_reference_rejected(tmp_path):
    bad = _MULTI.replace("datastore: warehouse", "datastore: nope")
    with pytest.raises(ConfigErrors) as exc:
        _parse(bad, tmp_path)
    assert any(e.code == "DATASTORE_UNKNOWN_REFERENCE" for e in exc.value.errors)


def test_postgres_datastore_requires_dsn(tmp_path):
    bad = _MULTI.replace(', dsn: "postgresql+asyncpg://localhost/wh"', "")
    with pytest.raises(ConfigErrors) as exc:
        _parse(bad, tmp_path)
    assert any(e.code == "DATASTORE_MISSING_DSN" for e in exc.value.errors)


def test_multiple_datastores_require_explicit_default(tmp_path):
    bad = _MULTI.replace("{ type: mongodb, default: true }", "{ type: mongodb }")
    with pytest.raises(ConfigErrors) as exc:
        _parse(bad, tmp_path)
    assert any(e.code == "DATASTORE_NO_DEFAULT" for e in exc.value.errors)


_OP_SPEC = """
    version: "0.2"
    api: { basePath: /api }
    datastores:
      main: { type: mongodb, default: true }
      warehouse: { type: postgres, dsn: "postgresql+asyncpg://localhost/wh" }
    entities:
      event: { fields: { id: { type: id }, kind: { type: string } } }
    repositories:
      events:
        entity: event
        datastore: warehouse
        operations:
          OP_BODY
    services: { events: { repository: events } }
    controllers:
      events:
        base_path: /events
        routes: { list: { service: events, method: GET, path: "", access: public } }
"""


def test_mongo_command_on_postgres_rejected(tmp_path):
    spec = _OP_SPEC.replace(
        "OP_BODY", "byKind: { query: { command: find, filter: {} } }"
    )
    with pytest.raises(ConfigErrors) as exc:
        _parse(spec, tmp_path)
    assert any(e.code == "QUERY_FORM_MISMATCH" for e in exc.value.errors)


def test_sql_query_on_postgres_accepted(tmp_path):
    spec = _OP_SPEC.replace(
        "OP_BODY", 'byKind: { query: { sql: "SELECT * FROM events" } }'
    )
    ir = _parse(spec, tmp_path)
    assert "byKind" in ir.repositories["events"].operations


def test_sql_query_on_mongo_rejected(tmp_path):
    spec = _OP_SPEC.replace("datastore: warehouse", "datastore: main").replace(
        "OP_BODY", 'byKind: { query: { sql: "SELECT 1" } }'
    )
    with pytest.raises(ConfigErrors) as exc:
        _parse(spec, tmp_path)
    assert any(e.code == "QUERY_FORM_MISMATCH" for e in exc.value.errors)
