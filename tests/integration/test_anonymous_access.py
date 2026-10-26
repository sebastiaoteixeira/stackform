"""A route closed to anonymous callers stays closed when the spec declares no identity, on every server and target."""

import pytest
from starlette.testclient import TestClient

from tests.unit.support.generated_apps import run_generated, write_spec
from yaml_api_generator.server import build_app, build_raw_app

pytestmark = pytest.mark.integration

_V01 = """
version: "0.1"
api: {{ basePath: /api }}
mongo: {{ uri: "{uri}", database: {database} }}
collections:
  posts:
    access: {{ list: public, create: "*" }}
    fields:
      id: {{ type: id }}
      title: {{ type: string, required: true }}
"""

_V0X = """
version: "{version}"
api: {{ basePath: /api }}
mongo: {{ uri: "{uri}", database: {database} }}
entities:
  post:
    fields:
      id: {{ type: id }}
      title: {{ type: string, required: true }}
repositories:
  posts: {{ entity: post }}
services:
  list_posts: {{ repository: posts, operation: list }}
  create_post: {{ repository: posts, operation: create }}
controllers:
  posts:
    base_path: /posts
    routes:
      list: {{ service: list_posts, method: GET, path: "", access: public }}
      create: {{ service: create_post, method: POST, path: "", access: "*" }}
"""

SPECS = {"0.1": _V01, "0.2": _V0X, "0.3": _V0X}
EXPECTED = {"list": 200, "create": 401}
_VERSIONS = pytest.mark.parametrize("version", SPECS)


def exercise(client) -> dict[str, int]:
    return {
        "list": client.get("/api/posts").status_code,
        "create": client.post("/api/posts", json={"title": "anonymous"}).status_code,
    }


def _spec(tmp_path, version, mongo_uri, mongo_database):
    return write_spec(tmp_path, SPECS[version].format(version=version, uri=mongo_uri, database=mongo_database))


@_VERSIONS
@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["dev", "devraw"])
def test_dev_server(build, version, tmp_path, monkeypatch, mongo_uri, mongo_database):
    monkeypatch.setenv("YAML_API_MONGO_URI", mongo_uri)
    monkeypatch.setenv("YAML_API_MONGO_DB", mongo_database)
    with TestClient(build(str(_spec(tmp_path, version, mongo_uri, mongo_database)))) as client:
        assert exercise(client) == EXPECTED


@_VERSIONS
@pytest.mark.parametrize("target", ["fastapi", "raw", "drf"])
def test_generated(target, version, tmp_path, mongo_uri, mongo_database):
    script = """
    from tests.integration.test_anonymous_access import exercise

    with client:
        print(json.dumps(exercise(client)))
    """
    env = {"MONGO_URI": mongo_uri, "MONGO_DB": mongo_database, "DJANGO_SECRET_KEY": "test-secret"}
    assert run_generated(_spec(tmp_path, version, mongo_uri, mongo_database), target, script, env) == EXPECTED
