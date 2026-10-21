"""Valid and invalid request payloads, sent alike to every app under test.

The spec covers formats, array items, closed nested objects, defaults, readonly
fields, strict scalars, partial updates and a DTO-typed body, which an access
rule binds for any signed-in user.
"""

import textwrap

from starlette.testclient import TestClient


SQL_STORE = """
datastores:
  store:
    type: postgres
    dsn: "postgresql+asyncpg://localhost/unused"
    default: true
"""

MONGO_STORE = """
mongo:
  uri: mongodb://localhost:27017
  database: payloads
"""

JWT_SECRET = "payload-scenario-secret-of-at-least-32-bytes"

_API = """
version: "0.2"
api:
  basePath: ""
  operations:
    defaults: { list: true, get: true, create: true, update: true, delete: true }
    auth: { register: true, login: true }
"""

_ENTITIES = """
dto:
  noteInput:
    fields:
      role: { type: enum, values: [admin, member], required: true }
entities:
  user:
    type: auth
    auth: { identifier: email, via: password }
    fields:
      id: { type: id, format: uuidv4 }
      email: { type: string, required: true, unique: true }
  item:
    fields:
      id: { type: id, format: uuidv4 }
      name: { type: string, required: true, minLength: 2 }
      email: { type: string, format: email }
      status: { type: enum, values: [draft, live], default: draft }
      rank: { type: number }
      active: { type: boolean }
      stamp: { type: string, readonly: true }
      tags: { type: array, items: { type: string, maxLength: 3 } }
      meta:
        type: object
        properties:
          color: { type: string, required: true }
          size: { type: number, min: 1 }
        additionalProperties: false
  note:
    fields:
      id: { type: id, format: uuidv4 }
      role: { type: string }
repositories:
  users: { entity: user }
  items: { entity: item }
  notes: { entity: note }
services:
  users: { repository: users }
  items: { repository: items }
  notes: { repository: notes }
controllers:
  users:
    service: users
    base_path: /users
    access: "*"
    operations:
      register: { access: public }
      login: { access: public }
  items:
    service: items
    base_path: /items
    access: public
  notes:
    service: notes
    base_path: /notes
    operations:
      create:
        access:
          - given: { caller: "identity:user", note: "request.body:noteInput" }
"""

CREATES = [
    ({"name": "ab", "rank": 3, "active": True, "tags": ["abc"], "meta": {"color": "r", "size": 2}}, 200),
    ({"name": "ab", "email": "not-an-email"}, 422),
    ({"name": "ab", "tags": ["abcd"]}, 422),
    ({"name": "ab", "meta": {"color": "r", "extra": 1}}, 422),
    ({"name": "ab", "meta": {"size": 2}}, 422),
    ({"name": "ab", "meta": {"color": "r", "size": 0}}, 422),
    ({"name": "ab", "meta": {"color": "r", "size": "2"}}, 422),
    ({"name": "ab", "rank": "3"}, 422),
    ({"name": "ab", "active": "true"}, 422),
    ({"name": "ab", "active": 1}, 422),
    ({"name": "ab", "stamp": "x"}, 422),
    ({"name": "ab", "unknown": 1}, 422),
    ({"name": "a"}, 422),
    ({}, 422),
]
UPDATES = [
    ({}, 200),
    ({"meta": {"color": "b"}}, 200),
    ({"name": "a"}, 422),
    ({"name": None}, 422),
    ({"email": "x"}, 422),
    ({"stamp": "x"}, 422),
    ({"meta": {"size": 2}}, 422),
]
NOTES = [
    ({"role": "admin"}, 200),
    ({"role": "owner"}, 422),
    ({"role": "admin", "unknown": 1}, 422),
    ({}, 422),
]
EXPECTED = [
    *(["POST /items", body, status] for body, status in CREATES),
    *(["PATCH /items", body, status] for body, status in UPDATES),
    *(["POST /notes", body, status] for body, status in NOTES),
]


def spec(datastore: str) -> str:
    return _API + textwrap.dedent(datastore) + _ENTITIES


def _bearer(client: TestClient) -> dict[str, str]:
    login = {"email": "caller@example.com", "password": "caller-password"}
    assert client.post("/users/register", json=login).status_code == 200
    token = client.post("/users/login", json=login).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def scenario(client: TestClient) -> list[list]:
    """Each payload with the status it got, after one valid item is created for the updates."""
    headers = _bearer(client)
    created = client.post("/items", json={"name": "ab"})
    assert created.status_code == 200, created.text
    item = created.json()
    assert item["status"] == "draft", item
    return [
        *(["POST /items", body, client.post("/items", json=body).status_code] for body, _ in CREATES),
        *(
            ["PATCH /items", body, client.patch(f"/items/{item['id']}", json=body).status_code]
            for body, _ in UPDATES
        ),
        *(
            ["POST /notes", body, client.post("/notes", json=body, headers=headers).status_code]
            for body, _ in NOTES
        ),
    ]
