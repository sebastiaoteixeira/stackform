"""Role assignment, login exposure and readonly fields over real HTTP, in the dev server and the generated FastAPI app."""

import pytest

from tests.unit.support.live_apps import SERVERS, serve, write_spec

_SPEC = """
version: "0.3"
api:
  basePath: /api
  operations:
    auth: { register: true, login: false }
{datastore}
entities:
  user:
    type: auth
    auth: { identifier: email, via: password, roles: role }
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      role: { type: enum, values: [admin, member], default: member }
  account:
    type: auth
    auth: { identifier: email, via: password, roles: role }
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      role: { type: enum, values: [admin, member], default: member }
  member:
    type: auth
    auth: { identifier: email, via: password }
    roles: { values: [boss, peon], default: peon }
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
  note:
    fields:
      id: { type: id }
      title: { type: string }
      role: { type: string }
      roles: { type: string }
      stamp: { type: string, readonly: true }
repositories:
  users: { entity: user }
  accounts: { entity: account }
  members: { entity: member }
  notes: { entity: note }
services:
  users: { repository: users }
  accounts: { repository: accounts }
  members: { repository: members }
  notes: { repository: notes }
controllers:
  users:
    service: users
    base_path: /users
    access: user:admin
    operations:
      register: { access: public }
      create:
        access:
          - given: { principal: "identity:user" }
  accounts:
    service: accounts
    base_path: /accounts
    access: account:admin
    operations:
      create: { access: public }
  members:
    service: members
    base_path: /members
    access: member:peon
    operations:
      register: { access: public }
  notes:
    service: notes
    base_path: /notes
    access: public
"""

ADMIN = {"email": "admin@x.io", "password": "pw", "role": "admin"}


@pytest.fixture(scope="module", params=SERVERS, ids=lambda server: server.name)
def client(request, tmp_path_factory):
    with serve(request.param, write_spec(tmp_path_factory.mktemp(request.param.name), _SPEC)) as client:
        yield client


def _credentials(account):
    return account["email"], account["password"]


def test_anonymous_register_gets_the_default_role(client):
    response = client.post("/api/users/register", json={"email": "a@x.io", "password": "pw", "role": "admin"})

    assert response.status_code == 200
    assert response.json()["role"] == "member"
    assert client.get("/api/users", auth=("a@x.io", "pw")).status_code == 403


def test_anonymous_create_gets_the_default_role(client):
    response = client.post("/api/accounts", json={"email": "c@x.io", "password": "pw", "role": "admin"})

    assert response.json()["role"] == "member"
    assert client.get("/api/accounts", auth=("c@x.io", "pw")).status_code == 403


def test_authenticated_create_assigns_the_requested_role(client):
    client.post("/api/users/register", json={"email": "d@x.io", "password": "pw"})

    created = client.post("/api/users", json=ADMIN, auth=("d@x.io", "pw"))

    assert created.json()["role"] == "admin"
    assert client.get("/api/users", auth=_credentials(ADMIN)).status_code == 200


def test_managed_roles_start_at_the_default(client):
    client.post("/api/members/register", json={"email": "m@x.io", "password": "pw"})

    assert client.get("/api/members", auth=("m@x.io", "pw")).status_code == 200


def test_non_identity_role_fields_are_stored(client):
    note = client.post("/api/notes", json={"title": "t", "role": "editor", "roles": "all"}).json()

    stored = client.get(f"/api/notes/{note['id']}").json()
    assert (stored["role"], stored["roles"]) == ("editor", "all")


def test_readonly_fields_are_never_written_by_clients(client):
    client.post("/api/notes", json={"title": "forged", "stamp": "forged"})

    assert all(note.get("stamp") != "forged" for note in client.get("/api/notes").json())


def test_disabled_login_serves_no_login_route(client):
    client.post("/api/users/register", json={"email": "l@x.io", "password": "pw"})

    assert client.post("/api/users/login", json={"email": "l@x.io", "password": "pw"}).status_code in (404, 405)
