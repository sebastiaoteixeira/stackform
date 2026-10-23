"""Access rules over real HTTP, in the dev server and the generated FastAPI app."""

import pytest

from tests.unit.support.live_apps import SERVERS, serve, write_spec

_SPEC = """
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
  post:
    fields:
      id: { type: id }
      title: { type: string }
      ownerId: { type: string }
      archivedAt: { type: string }
repositories:
  users: { entity: user }
  posts: { entity: post }
services:
  users: { repository: users }
  posts: { repository: posts }
controllers:
  users:
    service: users
    base_path: /users
    access: public
  posts:
    base_path: /posts
    routes:
      create:
        service: posts
        method: POST
        path: ""
        access:
          - given: { principal: "identity:user" }
      list:
        service: posts
        method: GET
        path: ""
        access:
          - given: { principal: "identity:user", post: posts }
            when: post.ownerId equals principal.sub
      get:
        service: posts
        method: GET
        path: /{id}
        access:
          - given: { document: posts }
            when: document.archivedAt is not null
            then: deny
            reason: Archived posts are hidden.
          - then: allow
  live:
    base_path: /live
    routes:
      get:
        service: posts
        method: GET
        path: /{id}
        access:
          - given: { document: posts }
            when: document.archivedAt is null
  owned:
    base_path: /owned
    routes:
      get:
        service: posts
        method: GET
        path: /{ownerId}/{id}
        access:
          - given: { principal: "identity:user", owner: users by ownerId }
            when: owner.id equals principal.sub
"""


@pytest.fixture(scope="module", params=SERVERS, ids=lambda server: server.name)
def client(request, tmp_path_factory):
    with serve(request.param, write_spec(tmp_path_factory.mktemp(request.param.name), _SPEC)) as client:
        yield client


@pytest.fixture(scope="module")
def accounts(client):
    """Two users, each owning one post, as ``{email: (basic auth, user id, post)}``."""
    def account(email):
        user = client.post("/api/users/register", json={"email": email, "password": "pw"}).json()
        basic = (email, "pw")
        post = client.post("/api/posts", json={"title": email, "ownerId": user["id"]}, auth=basic).json()
        return basic, user["id"], post

    return {email: account(email) for email in ("ann@x.io", "bob@x.io")}


ARCHIVED = {"archivedAt": "2026-01-01"}


def _get(client, accounts, path, **fields):
    """As ann, GET ``path`` followed by the id of a new post of hers holding ``fields``."""
    basic = accounts["ann@x.io"][0]
    post = client.post("/api/posts", json={"title": "p", **fields}, auth=basic).json()
    return client.get(f"{path}/{post['id']}", auth=basic)


def test_list_returns_only_the_rows_the_rule_admits(client, accounts):
    basic, user_id, _ = accounts["ann@x.io"]

    rows = client.get("/api/posts", auth=basic).json()

    assert {row["ownerId"] for row in rows} == {user_id}


def test_document_binding_by_parameter_loads_the_named_record(client, accounts):
    ann, ann_id, ann_post = accounts["ann@x.io"]
    _, bob_id, bob_post = accounts["bob@x.io"]

    assert client.get(f"/api/owned/{ann_id}/{ann_post['id']}", auth=ann).status_code == 200
    assert client.get(f"/api/owned/{bob_id}/{bob_post['id']}", auth=ann).status_code == 403


@pytest.mark.parametrize(
    ("fields", "status"),
    [({"archivedAt": None}, 200), ({}, 200), (ARCHIVED, 403)],
    ids=["explicit-null", "absent", "set"],
)
def test_is_null_admits_null_and_absent_values_only(client, accounts, fields, status):
    assert _get(client, accounts, "/api/live", **fields).status_code == status


def test_is_not_null_admits_null_values(client, accounts):
    assert _get(client, accounts, "/api/posts", archivedAt=None).status_code == 200


def test_is_not_null_denies_set_values_with_the_rule_reason(client, accounts):
    response = _get(client, accounts, "/api/posts", **ARCHIVED)

    assert (response.status_code, response.json()["detail"]) == (403, "Archived posts are hidden.")
