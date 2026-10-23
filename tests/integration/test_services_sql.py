"""Services over SQL behave the same under `stackform run` and the FastAPI app it generates."""

import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from tests.integration.support.spec_apps import SQL_BACKENDS, serve

SPEC = Path(__file__).parent / "specs" / "services_sql"


@pytest.fixture(scope="module", params=SQL_BACKENDS, ids=lambda backend: backend.name)
def api(request, tmp_path_factory):
    workdir = tmp_path_factory.mktemp(request.param.name) / "spec"
    shutil.copytree(SPEC, workdir)
    with serve(request.param, workdir / "spec.yaml", {"SQL_DSN": f"sqlite+aiosqlite:///{workdir}/db.sqlite"}) as client:
        yield client


@pytest.fixture(scope="module")
def user(api):
    credentials = {"email": f"{uuid4().hex}@example.com", "password": "correct-horse-battery"}
    registered = api.post("/api/users", json=credentials).json()
    token = api.post("/api/users/login", json=credentials).json()["token"]
    return {"id": registered["id"], "headers": {"Authorization": f"Bearer {token}"}}


def _task(api) -> str:
    title = uuid4().hex
    assert api.post("/api/tasks", json={"title": title}).status_code == 200
    return title


def test_operation_inherited_from_abstract_repository_and_service_runs(api):
    before = api.get("/api/tasks/stats/count").json()[0]["total"]
    _task(api)
    assert api.get("/api/tasks/stats/count").json() == [{"total": before + 1}]


def test_declared_sql_operation_binds_the_path_parameter(api):
    title = _task(api)
    response = api.get(f"/api/tasks/by-title/{title}")
    assert response.status_code == 200
    assert response.json() == [{"title": title}]


def test_handler_receives_the_request_it_documents(api, user):
    response = api.post("/api/tasks/echo/t1?page=2", json={"note": "hi"}, headers=user["headers"])
    assert response.status_code == 200
    assert response.json() == {
        "params": {"id": "t1"},
        "query": {"page": "2"},
        "body": {"note": "hi"},
        "principal": {"sub": user["id"]},
        "inputs": {},
    }


def test_operation_access_override_guards_an_inherited_handler(api):
    assert api.post("/api/tasks/echo/t1", json={}).status_code == 401


def test_operation_disabled_by_the_abstract_service_is_not_routed(api):
    task = api.post("/api/tasks", json={"title": uuid4().hex}).json()
    assert api.delete(f"/api/tasks/{task['id']}").status_code == 405


def test_repository_crud_limits_the_routes(api):
    assert api.get("/api/notes/n1").status_code == 404
    assert api.get("/api/notes").status_code == 405


def test_controller_path_override_moves_the_route(api):
    response = api.get("/api/notes/all")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_controller_access_override_applies_to_one_operation(api, user):
    assert api.post("/api/notes", json={"body": "x"}).status_code == 401
    created = api.post("/api/notes", json={"body": "x"}, headers=user["headers"])
    assert created.status_code == 200
    assert created.json()["body"] == "x"


def test_minified_service_forwards_its_input_to_every_operation(api):
    title = _task(api)
    response = api.get(f"/api/titles/{title}")
    assert response.status_code == 200
    assert response.json() == [{"title": title}]
