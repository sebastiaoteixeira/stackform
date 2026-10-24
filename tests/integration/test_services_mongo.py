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


def test_single_segment_operation_path_outranks_the_record_route(api):
    before = api.get("/api/tasks/stats").json()
    _create(api, "tasks", title=uuid4().hex)
    assert api.get("/api/tasks/stats").json() == before + 1


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


@pytest.mark.parametrize(
    "send",
    [{}, {"json": None}, {"json": 0}, {"content": "plain", "headers": {"Content-Type": "text/plain"}}],
    ids=["absent", "null", "zero", "text"],
)
def test_handler_receives_an_empty_body_for_any_non_object_body(api, send):
    response = api.post("/api/tasks/echo/t1", **send)
    assert response.status_code == 200, response.text
    assert response.json()["body"] == {}


def test_handler_receives_the_last_value_of_a_repeated_query_key(api):
    response = api.post("/api/tasks/echo/t1?page=1&page=2")
    assert response.status_code == 200, response.text
    assert response.json()["query"] == {"page": "2"}

@pytest.fixture(scope="module")
def user(api):
    login = {"email": f"{uuid4().hex}@example.com", "password": "correct-horse-battery"}
    registered = api.post("/api/users", json=login).json()
    token = api.post("/api/users/login", json=login).json()["token"]
    return {"id": registered["id"], "email": login["email"], "headers": {"Authorization": f"Bearer {token}"}}


def test_controllers_sharing_a_service_keep_their_own_access(api, user):
    title = uuid4().hex
    _create(api, "tasks", title=title)
    assert api.get("/api/archive").status_code == 401
    assert api.get("/api/tasks").status_code == 200
    assert _titles(api.get(f"/api/archive/by-title/{title}", headers=user["headers"])) == [title]


def test_handler_principal_carries_the_identity_without_its_credentials(api, user):
    response = api.post("/api/archive/echo/t1", headers=user["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["principal"] == {
        "sub": user["id"],
        "identity_collection": "users",
        "roles": [],
        "record": {"id": user["id"], "email": user["email"]},
    }


def test_explicit_controller_route_is_public_at_its_overridden_path(api):
    response = api.get("/api/totals/tasks")
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), int)
    assert api.get("/api/tasks-total").status_code == 404
