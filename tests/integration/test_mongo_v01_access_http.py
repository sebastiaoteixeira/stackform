"""0.1 access rules that compare the caller with the record, served on MongoDB by the dev server and every generated backend."""

from uuid import uuid4

import pytest

from tests.unit.support.live_apps import MONGO_SERVERS, mongo, serve, write_spec

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
    access:
      create: public
      get: "*"
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
  posts:
    access:
      create: "*"
      list:
        - principal: "users:*"
          when: "principal.sub equals document.ownerId"
      get:
        - principal: "users:*"
          when: "principal.sub equals document.ownerId"
          reason: Owner only.
    fields:
      id: { type: id }
      title: { type: string }
      ownerId: { type: string }
"""

OWNER = ("owner@x.io", "pw")


@pytest.fixture(scope="module", params=MONGO_SERVERS, ids=lambda server: server.name)
def client(request, tmp_path_factory, mongo_uri):
    server = request.param
    spec = write_spec(tmp_path_factory.mktemp(server.name), SPEC, mongo(mongo_uri, f"{server.name}_{uuid4().hex}"))
    with serve(server, spec) as client:
        yield client


@pytest.fixture(scope="module")
def posts(client):
    """The owner's post and someone else's, by title."""
    email, password = OWNER
    owner = client.post("/api/users", json={"email": email, "password": password}).json()["id"]
    return {
        title: client.post("/api/posts", json={"title": title, "ownerId": owner_id}, auth=OWNER).json()["id"]
        for title, owner_id in (("mine", owner), ("theirs", "someone"))
    }


def test_owner_reads_its_record(client, posts):
    response = client.get(f"/api/posts/{posts['mine']}", auth=OWNER)
    assert (response.status_code, response.json()["title"]) == (200, "mine")


def test_refusal_carries_the_rule_reason(client, posts):
    response = client.get(f"/api/posts/{posts['theirs']}", auth=OWNER)
    assert (response.status_code, response.json()) == (403, {"detail": "Owner only."})


def test_list_holds_only_the_records_the_rule_admits(client, posts):
    response = client.get("/api/posts", auth=OWNER)
    assert [row["title"] for row in response.json()] == ["mine"]
