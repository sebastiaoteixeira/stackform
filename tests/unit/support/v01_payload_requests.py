"""Valid and invalid request payloads for a v0.1 collection, sent alike to every app under test.

A v0.1 spec declares its model keys on collection fields; the apps start from
its ``mongo`` block and validate formats, items, closed nested objects,
defaults, number bounds and datetimes as v0.2 entities do.
"""

from starlette.testclient import TestClient


def spec(uri: str, database: str) -> str:
    return f"""
version: "0.1"
api:
  basePath: ""
  operations:
    defaults: {{ list: true, get: true, create: true, update: true, replace: true, delete: true }}
mongo:
  uri: {uri}
  database: {database}
collections:
  things:
    fields:
      id: {{ type: id }}
      name: {{ type: string, required: true, minLength: 2 }}
      email: {{ type: string, format: email }}
      status: {{ type: enum, values: [draft, live], default: draft }}
      count: {{ type: number, min: 0 }}
      when: {{ type: datetime }}
      tags: {{ type: array, items: {{ type: string, maxLength: 3 }} }}
      meta:
        type: object
        properties:
          color: {{ type: string, required: true }}
        additionalProperties: false
"""


CREATES = [
    ({"name": "ab", "meta": {"color": "r"}, "tags": ["abc"], "count": 0}, 200),
    ({"name": "a"}, 422),
    ({"name": "ab", "email": "x"}, 422),
    ({"name": "ab", "tags": ["abcd"]}, 422),
    ({"name": "ab", "meta": {"color": "r", "x": 1}}, 422),
    ({"name": "ab", "meta": {}}, 422),
    ({"name": "ab", "count": -1}, 422),
    ({"name": "ab", "count": "3"}, 422),
    ({"name": "ab", "when": 1700000000}, 422),
    ({"name": "ab", "status": "gone"}, 422),
    ({"name": "ab", "unknown": 1}, 422),
]
ROUND_TRIPS = [
    ["default stored", "draft"],
    ["date-only datetime canonical", "2024-01-01T00:00:00+00:00"],
    ["partial update", [200, 2, "ab"]],
    ["replaced", [200, "cd"]],
    ["deleted", [200, 404]],
]
EXPECTED = [*(["POST /things", body, status] for body, status in CREATES), *ROUND_TRIPS]


def scenario(client: TestClient) -> list[list]:
    created = client.post("/things", json={"name": "ab", "when": "2024-01-01"}).json()
    path = f"/things/{created['id']}"
    patched = client.patch(path, json={"count": 2})
    replaced = client.put(path, json={"name": "cd"})
    return [
        *(["POST /things", body, client.post("/things", json=body).status_code] for body, _ in CREATES),
        ["default stored", client.get(path).json()["status"]],
        ["date-only datetime canonical", created["when"]],
        ["partial update", [patched.status_code, patched.json()["count"], patched.json()["name"]]],
        ["replaced", [replaced.status_code, client.get(path).json()["name"]]],
        ["deleted", [client.delete(path).status_code, client.get(path).status_code]],
    ]
