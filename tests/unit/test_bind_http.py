"""Access-rule ``bind:`` on repository writes over real HTTP, in the dev server and the generated FastAPI app."""

import pytest

from tests.unit.support.live_apps import SERVERS, serve, write_spec

SPEC = """
version: "0.3"
api:
  basePath: /api
  operations:
    auth: { register: true }
{datastore}
entities:
  user:
    type: auth
    auth: { identifier: email, via: password }
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
  doc:
    fields:
      id: { type: id }
      title: { type: string }
      ownerRef: { type: string }
      organizationId: { type: string, readonly: true }
repositories:
  users: { entity: user }
  docs: { entity: doc }
services:
  users: { repository: users }
  docs: { repository: docs }
  ownedDocs:
    repository: docs
    operation: create
    input:
      title: { type: string, required: false }
      ownerRef: string
      organizationId: string
controllers:
  users:
    service: users
    base_path: /users
    access: public
  docs:
    service: docs
    base_path: /docs
    access: public
    operations:
      create: { access: none }
  owned:
    base_path: /owned
    routes:
      create:
        service: ownedDocs
        method: POST
        path: ""
        access:
          - given: { principal: "identity:user" }
            bind:
              ownerRef: $principal.sub
              organizationId: acme
"""


@pytest.fixture(scope="module", params=SERVERS, ids=lambda server: server.name)
def client(request, tmp_path_factory):
    with serve(request.param, write_spec(tmp_path_factory.mktemp(request.param.name), SPEC)) as client:
        yield client


@pytest.fixture(scope="module")
def caller(client):
    """A registered user, as ``(basic auth, user id)``."""
    user = client.post("/api/users/register", json={"email": "b@x.io", "password": "pw"}).json()
    return ("b@x.io", "pw"), user["id"]


def _stored(client, created):
    assert created.status_code == 200, created.text
    return client.get(f"/api/docs/{created.json()['id']}").json()


def test_bind_overrides_the_body_on_create(client, caller):
    basic, user_id = caller

    stored = _stored(client, client.post("/api/owned", json={"title": "t", "ownerRef": "forged"}, auth=basic))

    assert stored["ownerRef"] == user_id


def test_bind_supplies_an_input_the_body_omits(client, caller):
    basic, user_id = caller

    stored = _stored(client, client.post("/api/owned", json={"title": "t"}, auth=basic))

    assert stored["ownerRef"] == user_id


def test_bind_writes_a_readonly_field(client, caller):
    basic, _ = caller

    stored = _stored(client, client.post("/api/owned", json={"title": "t"}, auth=basic))

    assert stored["organizationId"] == "acme"
