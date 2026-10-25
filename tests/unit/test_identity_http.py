"""Role assignment, login exposure and readonly fields over real HTTP, in the dev server and the generated FastAPI app."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

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
      update:
        access:
          - given: { principal: "identity:user", document: users }
            when: document.id equals principal.sub
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

ADMIN = {"email": "admin@x.io", "password": "pw"}


def seed_admin(client, promote: Callable[[str], None]) -> None:
    """Register ``ADMIN`` and raise it to admin in the store, past every route."""
    client.post("/api/users/register", json=ADMIN)
    promote(ADMIN["email"])


def _promote_in_sqlite(store: Path, email: str) -> None:
    with closing(sqlite3.connect(store)) as db, db:
        db.execute("UPDATE users SET role = 'admin' WHERE email = ?", (email,))


@pytest.fixture(scope="module", params=SERVERS, ids=lambda server: server.name)
def client(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp(request.param.name)
    with serve(request.param, write_spec(directory, _SPEC)) as client:
        seed_admin(client, lambda email: _promote_in_sqlite(directory / "store.sqlite", email))
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


def test_create_assigns_a_requested_role_its_caller_holds(client):
    created = client.post("/api/users", json={"email": "d@x.io", "password": "pw", "role": "admin"}, auth=_credentials(ADMIN))

    assert created.json()["role"] == "admin"
    assert client.get("/api/users", auth=("d@x.io", "pw")).status_code == 200


def test_create_gives_the_default_for_a_role_its_caller_lacks(client):
    client.post("/api/users/register", json={"email": "e@x.io", "password": "pw"})

    created = client.post("/api/users", json={"email": "f@x.io", "password": "pw", "role": "admin"}, auth=("e@x.io", "pw"))

    assert created.json()["role"] == "member"
    assert client.get("/api/users", auth=("f@x.io", "pw")).status_code == 403


def test_update_never_raises_a_role_its_caller_lacks(client):
    me = client.post("/api/users/register", json={"email": "g@x.io", "password": "pw"}).json()

    updated = client.patch(f"/api/users/{me['id']}", json={"role": "admin"}, auth=("g@x.io", "pw"))

    assert (updated.status_code, updated.json()["role"]) == (200, "member")
    assert client.get("/api/users", auth=("g@x.io", "pw")).status_code == 403


def test_managed_roles_start_at_the_default(client):
    client.post("/api/members/register", json={"email": "m@x.io", "password": "pw"})

    assert client.get("/api/members", auth=("m@x.io", "pw")).status_code == 200


def test_non_identity_role_fields_are_stored(client):
    note = client.post("/api/notes", json={"title": "t", "role": "editor", "roles": "all"}).json()

    stored = client.get(f"/api/notes/{note['id']}").json()
    assert (stored["role"], stored["roles"]) == ("editor", "all")


def test_readonly_fields_are_refused_on_every_write(client):
    note = client.post("/api/notes", json={"title": "t"}).json()

    writes = [
        client.post("/api/notes", json={"title": "forged", "stamp": "forged"}),
        client.patch(f"/api/notes/{note['id']}", json={"stamp": "forged"}),
        client.put(f"/api/notes/{note['id']}", json={"title": "forged", "stamp": "forged"}),
    ]

    assert [write.status_code for write in writes] == [422, 422, 422]
    assert all(note.get("stamp") != "forged" for note in client.get("/api/notes").json())


def test_an_empty_update_returns_the_record_unchanged(client):
    note = client.post("/api/notes", json={"title": "t"}).json()

    updated = client.patch(f"/api/notes/{note['id']}", json={})

    assert (updated.status_code, updated.json()["title"]) == (200, "t")


def test_replace_keeps_the_record_under_its_id(client):
    note = client.post("/api/notes", json={"title": "t"}).json()

    replaced = client.put(f"/api/notes/{note['id']}", json={"title": "u"})

    assert replaced.json()["id"] == note["id"]
    assert client.get(f"/api/notes/{note['id']}").json()["title"] == "u"


def test_credentials_never_leave_the_server(client):
    registered = client.post("/api/users/register", json={"email": "s@x.io", "password": "pw"}).json()

    responses = [registered, *client.get("/api/users", auth=_credentials(ADMIN)).json()]

    assert not any({"_auth", "password", "passwordHash"} & set(user) for user in responses)


def test_disabled_login_serves_no_login_route(client):
    client.post("/api/users/register", json={"email": "l@x.io", "password": "pw"})

    assert client.post("/api/users/login", json={"email": "l@x.io", "password": "pw"}).status_code in (404, 405)
