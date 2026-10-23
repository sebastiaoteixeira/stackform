"""Services over MongoDB behave the same under `stackform run` and every backend it generates."""

import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from tests.integration.support.spec_apps import MONGO_BACKENDS, serve

pytestmark = pytest.mark.integration

SPEC = Path(__file__).parent / "specs" / "services_mongo"


@pytest.fixture(scope="module", params=MONGO_BACKENDS, ids=lambda backend: backend.name)
def api(request, tmp_path_factory, mongo_uri):
    workdir = tmp_path_factory.mktemp(request.param.name) / "spec"
    shutil.copytree(SPEC, workdir)
    env = {"MONGO_URI": mongo_uri, "MONGO_DB": f"services_{uuid4().hex}"}
    with serve(request.param, workdir / "spec.yaml", env) as client:
        yield client


def _create(api, collection: str, **document) -> dict:
    response = api.post(f"/api/{collection}", json=document)
    assert response.status_code == 200, response.text
    return response.json()


def _titles(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [document["title"] for document in response.json()]


def test_find_operation_binds_the_path_parameter(api):
    title = uuid4().hex
    _create(api, "tasks", title=title)
    assert _titles(api.get(f"/api/tasks/by-title/{title}")) == [title]


def test_operation_reads_the_collection_its_query_names(api):
    body = uuid4().hex
    _create(api, "notes", body=body)
    response = api.get(f"/api/tasks/notes/{body}")
    assert response.status_code == 200, response.text
    assert [document["body"] for document in response.json()] == [body]


def test_bulk_write_applies_its_requests(api):
    old, new = uuid4().hex, uuid4().hex
    _create(api, "tasks", title=old)
    _create(api, "tasks", title=old)
    response = api.post(f"/api/tasks/retitle/{old}/{new}")
    assert response.status_code == 200, response.text
    assert response.json() == {"inserted": 0, "matched": 2, "modified": 2, "deleted": 0, "upserted": 0}
    assert _titles(api.get(f"/api/tasks/by-title/{new}")) == [new, new]


def test_handler_receives_the_request_it_documents(api):
    response = api.post("/api/tasks/echo/t1?page=2", json={"note": "hi"})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "params": {"id": "t1"},
        "query": {"page": "2"},
        "body": {"note": "hi"},
        "principal": None,
        "inputs": {},
    }
