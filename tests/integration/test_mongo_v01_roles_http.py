"""0.1 collection roles and access, served on MongoDB by the dev server and every generated backend, and shown by the UI."""

from uuid import uuid4

import pytest

from tests.unit.support.live_apps import MONGO_SERVERS, mongo, serve, write_spec
from yaml_api_generator.generators.frontend.packs.loader import load_pack
from yaml_api_generator.parsers.ui_parser import build_generator_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

pytestmark = pytest.mark.integration

SPEC = """
version: "0.1"
api:
  basePath: /api
{datastore}
collections:
  users:
    type: auth
    auth: { identifier: email, via: password }
    roles: { values: [admin, user], default: admin, hierarchy: { admin: [user] } }
    access:
      create: public
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
  posts:
    access:
      create: "users:user"
      get: public
      update: "users:user"
    fields:
      id: { type: id }
      title: { type: string, required: true }
"""

ADMIN = ("admin@x.io", "pw")


@pytest.fixture(scope="module", params=MONGO_SERVERS, ids=lambda server: server.name)
def client(request, tmp_path_factory, mongo_uri):
    server = request.param
    spec = write_spec(tmp_path_factory.mktemp(server.name), SPEC, mongo(mongo_uri, f"{server.name}_{uuid4().hex}"))
    with serve(server, spec) as client:
        client.post("/api/users", json={"email": ADMIN[0], "password": ADMIN[1]}).raise_for_status()
        yield client


@pytest.fixture(scope="module")
def post(client):
    return client.post("/api/posts", json={"title": "first"}, auth=ADMIN)


def test_role_includes_the_roles_its_hierarchy_names(post):
    assert post.status_code == 200


def test_replace_without_access_of_its_own_takes_update_access(client, post):
    url = f"/api/posts/{post.json()['id']}"

    assert [
        client.put(url, json={"title": "anonymous"}).status_code,
        client.put(url, json={"title": "admin"}, auth=ADMIN).status_code,
    ] == [401, 200]


def test_ui_shows_the_collection_roles(tmp_path, mongo_uri):
    ir = load_and_generate_ir(str(write_spec(tmp_path, SPEC, mongo(mongo_uri, "ui")))).ir
    context = build_generator_context(ir, {}, load_pack("generic").manifest)
    roles = context.entities["users"].roles

    assert (roles.values, roles.includes["admin"]) == (("admin", "user"), ("user",))
