"""Access rules over real HTTP, in the dev server and the generated FastAPI app, for every spec version that declares them."""

import itertools
from contextlib import contextmanager

import pytest

from tests.unit.support.live_apps import SERVERS, serve, write_spec

_SPEC = """
version: "{version}"
api:
  basePath: /api
  operations:
    auth: { register: true }
{datastore}
dto:
  draftInput:
    fields:
      title: { type: string }
      ownerId: { type: string }
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
  comment:
    fields:
      id: { type: id }
      postId: { type: string }
      text: { type: string }
  draft:
    fields:
      id: { type: id }
      title: { type: string }
      ownerId: { type: string }
repositories:
  users: { entity: user }
  posts: { entity: post }
  comments: { entity: comment }
  drafts: { entity: draft }
services:
  users: { repository: users }
  posts: { repository: posts }
  comments: { repository: comments }
  drafts: { repository: drafts }
  publish: { handler: handlers.publish }
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
  publish:
    base_path: /publish
    routes:
      run:
        service: publish
        method: POST
        path: /{id}
        access:
          - given: { principal: "identity:user", document: posts }
            when: document.ownerId equals principal.sub
  comments:
    base_path: /posts
    routes:
      create:
        service: comments
        method: POST
        path: /{postId}/comments
        access:
          - given: { principal: "identity:user", parent: posts by postId }
            when: parent.ownerId equals principal.sub
      list:
        service: comments
        method: GET
        path: /{postId}/comments
        access:
          - given: { principal: "identity:user", parent: posts by postId }
            when: parent.ownerId equals principal.sub
      get:
        service: comments
        method: GET
        path: /{postId}/comments/{id}
        access:
          - given: { principal: "identity:user", parent: posts by postId }
            when: parent.ownerId equals principal.sub
      delete:
        service: comments
        method: DELETE
        path: /{postId}/comments/{id}
        access:
          - given: { principal: "identity:user", parent: posts by postId }
            when: parent.ownerId equals principal.sub
  drafts:
    base_path: /drafts
    routes:
      create:
        service: drafts
        method: POST
        path: ""
        access:
          - given: { body: request.body }
            when: body.ownerId is not null
            then: deny
            reason: Drafts start without an owner.
          - then: allow
  owners:
    base_path: /owners
    routes:
      create:
        service: drafts
        method: POST
        path: /{ownerId}/drafts
        access:
          - given: { req: "request:draftInput" }
            when: req.body.ownerId equals req.path.ownerId
"""

# The dev server hands a handler its request context; a generated backend hands it the request
_HANDLERS = '''
async def publish(target):
    if hasattr(target, "response"):
        target.response = {"published": True}
        return target
    return {"published": True}
'''

VERSIONS = ("0.2", "0.3")
CASES = list(itertools.product(SERVERS, VERSIONS))


def case_id(case):
    server, version = case
    return f"{server.name}-{version}"


@contextmanager
def serving(server, version, directory, datastore=None):
    """``server`` serving the spec at ``version``, its handlers module beside it."""
    (directory / "handlers.py").write_text(_HANDLERS)
    spec = write_spec(directory, _SPEC.replace("{version}", version), datastore)
    with serve(server, spec, env={"PYTHONPATH": str(directory)}) as client:
        yield client


@pytest.fixture(scope="module", params=CASES, ids=case_id)
def client(request, tmp_path_factory):
    server, version = request.param
    with serving(server, version, tmp_path_factory.mktemp(case_id(request.param))) as client:
        yield client


@pytest.fixture(scope="module")
def accounts(client):
    """Two users, each owning one post with one comment, as ``{email: (basic auth, user id, post, comment)}``."""
    def account(email):
        user = client.post("/api/users/register", json={"email": email, "password": "pw"}).json()
        basic = (email, "pw")
        post = client.post("/api/posts", json={"title": email, "ownerId": user["id"]}, auth=basic).json()
        comment = client.post(f"/api/posts/{post['id']}/comments", json={"text": email}, auth=basic).json()
        return basic, user["id"], post, comment

    return {email: account(email) for email in ("ann@x.io", "bob@x.io")}


ARCHIVED = {"archivedAt": "2026-01-01"}


def _get(client, accounts, path, **fields):
    """As ann, GET ``path`` followed by the id of a new post of hers holding ``fields``."""
    basic = accounts["ann@x.io"][0]
    post = client.post("/api/posts", json={"title": "p", **fields}, auth=basic).json()
    return client.get(f"{path}/{post['id']}", auth=basic)


def test_list_returns_only_the_rows_the_rule_admits(client, accounts):
    basic, user_id, *_ = accounts["ann@x.io"]

    rows = client.get("/api/posts", auth=basic).json()

    assert {row["ownerId"] for row in rows} == {user_id}


def test_document_binding_by_parameter_loads_the_named_record(client, accounts):
    ann, ann_id, ann_post, _ = accounts["ann@x.io"]
    _, bob_id, bob_post, _ = accounts["bob@x.io"]

    assert client.get(f"/api/owned/{ann_id}/{ann_post['id']}", auth=ann).status_code == 200
    assert client.get(f"/api/owned/{bob_id}/{bob_post['id']}", auth=ann).status_code == 403


def test_path_parameters_naming_fields_scope_the_record(client, accounts):
    ann, ann_id, _, _ = accounts["ann@x.io"]
    _, _, bob_post, _ = accounts["bob@x.io"]

    assert client.get(f"/api/owned/{ann_id}/{bob_post['id']}", auth=ann).status_code == 404


def test_nested_create_checks_the_parent_and_stores_its_id(client, accounts):
    ann, _, ann_post, ann_comment = accounts["ann@x.io"]
    _, _, bob_post, _ = accounts["bob@x.io"]

    assert ann_comment["postId"] == ann_post["id"]
    assert client.post(f"/api/posts/{bob_post['id']}/comments", json={"text": "x"}, auth=ann).status_code == 403


def test_nested_list_returns_only_the_parent_rows(client, accounts):
    ann, _, ann_post, ann_comment = accounts["ann@x.io"]

    rows = client.get(f"/api/posts/{ann_post['id']}/comments", auth=ann).json()

    assert [row["id"] for row in rows] == [ann_comment["id"]]


def test_nested_detail_routes_only_reach_the_parent_rows(client, accounts):
    ann, _, ann_post, _ = accounts["ann@x.io"]
    bob, _, bob_post, bob_comment = accounts["bob@x.io"]
    foreign = f"/api/posts/{ann_post['id']}/comments/{bob_comment['id']}"

    assert client.get(foreign, auth=ann).status_code == 404
    assert client.delete(foreign, auth=ann).status_code == 404
    assert client.get(f"/api/posts/{bob_post['id']}/comments/{bob_comment['id']}", auth=bob).status_code == 200


def test_handler_route_binds_the_route_record(client, accounts):
    ann, _, ann_post, _ = accounts["ann@x.io"]
    _, _, bob_post, _ = accounts["bob@x.io"]

    published = client.post(f"/api/publish/{ann_post['id']}", auth=ann)

    assert (published.status_code, published.json()) == (200, {"published": True})
    assert client.post(f"/api/publish/{bob_post['id']}", auth=ann).status_code == 403


def test_unconditional_allow_admits_anonymous_callers(client, accounts):
    _, _, ann_post, _ = accounts["ann@x.io"]

    assert client.get(f"/api/posts/{ann_post['id']}").status_code == 200
    assert client.post("/api/drafts", json={"title": "t"}).status_code == 200


def test_typed_request_binding_reads_every_part(client):
    assert client.post("/api/owners/u1/drafts", json={"title": "t", "ownerId": "u1"}).status_code == 200
    assert client.post("/api/owners/u1/drafts", json={"title": "t", "ownerId": "u2"}).status_code == 401


def test_request_is_null_holds_for_absent_body_fields(client):
    denied = client.post("/api/drafts", json={"title": "t", "ownerId": "u"})

    assert client.post("/api/drafts", json={"title": "t"}).status_code == 200
    assert (denied.status_code, denied.json()["detail"]) == (403, "Drafts start without an owner.")


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
