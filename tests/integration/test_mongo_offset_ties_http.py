"""Offset pages over tied sort values, on MongoDB, cover every row exactly once in every server."""

from uuid import uuid4

import pytest

from tests.unit.support.live_apps import MONGO_SERVERS, serve, write_spec

pytestmark = pytest.mark.integration

SPEC = """
version: "0.3"
api:
  basePath: /api
datastores:
  store: { type: mongodb, uri: "{uri}", database: {database}, default: true }
entities:
  item:
    fields:
      id: { type: id }
      rank: { type: number, required: true }
repositories:
  items: { entity: item }
services:
  items: { repository: items }
controllers:
  items:
    service: items
    base_path: /items
    access: public
    operations:
      list:
        pagination: { strategy: offset, size: { default: 2, max: 2 }, sort: [{ field: rank, dir: desc }] }
"""


@pytest.mark.parametrize("server", MONGO_SERVERS, ids=lambda server: server.name)
def test_offset_pages_over_tied_values_are_disjoint_and_complete(server, tmp_path, mongo_uri):
    spec = write_spec(tmp_path, SPEC.replace("{uri}", mongo_uri).replace("{database}", f"ties_{uuid4().hex}"))
    with serve(server, spec) as client:
        created = {client.post("/api/items", json={"rank": 1}).json()["id"] for _ in range(7)}
        pages = [client.get("/api/items", params={"offset": offset}).json() for offset in range(0, 8, 2)]

    assert sorted(row["id"] for page in pages for row in page) == sorted(created)
