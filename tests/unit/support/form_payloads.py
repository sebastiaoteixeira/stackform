"""Bodies the generated UI sends for the payload scenario's items, sent alike to every app under test.

The generated `fields` module, run by Node from the path in ``FIELDS_MODULE``,
turns what a user enters into each body: a create form, an edit form loaded
from the stored record, a spreadsheet cell and a bulk edit of two fields.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from starlette.testclient import TestClient

from tests.unit.support import payload_requests

FIELDS_MODULE = "UI_FIELDS_MODULE"
NODE = shutil.which("node")

_DRIVER = Path(__file__).with_suffix(".ts")

_UI = """
ui:
  frontend: { pack: generic }
  views:
    items: { path: /items, component: crud, props: { collection: item } }
    sectioned: { path: /sectioned, component: crud, props: { collection: item, form: form-sectioned } }
    previewed: { path: /previewed, component: crud, props: { collection: item, form: form-preview } }
    modal: { path: /modal, component: crud, props: { collection: item, form: form-modal } }
    rows: { path: /rows, component: form-inline-row, props: { collection: item } }
    sheet: { path: /sheet, component: list-spreadsheet, props: { collection: item } }
    bulk: { path: /bulk, component: bulk-edit-drawer, props: { collection: item } }
"""

CREATE_INPUTS = {
    "name": "ab",
    "email": "a@b.co",
    "rank": "3",
    "active": True,
    "due": "2024-01-01T10:00",
    "tags": '["abc"]',
    "meta": '{"color": "r", "size": 2}',
    "points": '[{"x": 1}]',
}

EXPECTED = [
    ["create", 200],
    ["typed values stored", [3, True, "2024-01-01T10:00:00+00:00", "draft"]],
    ["edit", 200],
    ["edit keeps record", True],
    ["cell", 200, 7],
    ["bulk", 200, ["live", False]],
]


def spec(datastore: str) -> str:
    return payload_requests.spec(datastore) + _UI


def _form(**submission) -> dict:
    result = subprocess.run(
        [NODE, "--experimental-strip-types", "--no-warnings", str(_DRIVER), os.environ[FIELDS_MODULE]],
        input=json.dumps({"entity": "item", **submission}),
        env={**os.environ, "TZ": "UTC"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def scenario(client: TestClient) -> list[list]:
    """The status and stored values of each body the UI sends for one item."""
    created = client.post("/items", json=_form(inputs=CREATE_INPUTS))
    assert created.status_code == 200, created.text
    path = f"/items/{created.json()['id']}"
    record = client.get(path).json()
    edited = client.put(path, json=_form(record=record))
    cell = client.patch(path, json=_form(fields=["rank"], inputs={"rank": "7"}))
    bulk = client.patch(path, json=_form(fields=["status", "active"], inputs={"status": "live", "active": False}))
    return [
        ["create", created.status_code],
        ["typed values stored", [record["rank"], record["active"], record["due"], record["status"]]],
        ["edit", edited.status_code],
        ["edit keeps record", edited.json() == record],
        ["cell", cell.status_code, cell.json().get("rank")],
        ["bulk", bulk.status_code, [bulk.json().get("status"), bulk.json().get("active")]],
    ]
