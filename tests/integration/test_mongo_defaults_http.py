"""Declared field defaults fill what a create leaves out, on MongoDB, in every server."""

import itertools
from uuid import uuid4

import pytest

from tests.unit.support.live_apps import MONGO_SERVERS, serve, write_spec

pytestmark = pytest.mark.integration

SPEC = """
version: "{version}"
api:
  basePath: /api
datastores:
  store: { type: mongodb, uri: "{uri}", database: {database}, default: true }
entities:
  item:
    fields:
      id: { type: id }
      name: { type: string, required: true }
      active: { type: boolean, default: true }
      hidden: { type: boolean, default: false }
      rank: { type: number, default: 3 }
      status: { type: enum, values: [draft, live], default: draft }
repositories:
  items: { entity: item }
services:
  items: { repository: items }
controllers:
  items: { service: items, base_path: /items, access: public }
"""


@pytest.mark.parametrize(
    ("server", "version"), itertools.product(MONGO_SERVERS, ("0.2", "0.3")), ids=lambda value: getattr(value, "name", value)
)
def test_create_fills_every_declared_default(server, version, tmp_path, mongo_uri):
    spec = SPEC.replace("{version}", version).replace("{uri}", mongo_uri).replace("{database}", f"defaults_{uuid4().hex}")
    with serve(server, write_spec(tmp_path, spec)) as client:
        created = client.post("/api/items", json={"name": "a"}).json()

    assert {key: created[key] for key in ("active", "hidden", "rank", "status")} == {
        "active": True, "hidden": False, "rank": 3, "status": "draft"
    }
