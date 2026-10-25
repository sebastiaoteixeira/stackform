"""Services over SQL behave the same under `stackform run` and the FastAPI app it generates."""

import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from tests.integration.support.postgres import fresh_database
from tests.integration.support.spec_apps import SQL_BACKENDS, serve

SPEC = Path(__file__).parent / "specs" / "services_sql"


@contextmanager
def _sqlite(request, workdir):
    yield f"sqlite+aiosqlite:///{workdir}/db.sqlite"


@contextmanager
def _postgres(request, workdir):
    with fresh_database(request.getfixturevalue("postgres_uri")) as dsn:
        yield dsn


STORES = {"sqlite": _sqlite, "postgres": _postgres}


@pytest.fixture(
    scope="module",
    params=[(backend, store) for backend in SQL_BACKENDS for store in STORES],
    ids=lambda param: f"{param[0].name}-{param[1]}",
)
def api(request, tmp_path_factory):
    backend, store = request.param
    workdir = tmp_path_factory.mktemp(f"{backend.name}-{store}") / "spec"
    shutil.copytree(SPEC, workdir)
    with STORES[store](request, workdir) as dsn, serve(backend, workdir / "spec.yaml", {"SQL_DSN": dsn}) as client:
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


def test_numbers_keep_their_json_type_through_crud_and_declared_operations(api):
    title = uuid4().hex
    created = api.post("/api/tasks", json={"title": title, "score": 2.5}).json()
    assert created["score"] == 2.5
    assert api.get(f"/api/tasks/{created['id']}").json()["score"] == 2.5
    assert api.get(f"/api/tasks/scores/{title}").json() == [{"score": 2.5}]
    assert type(api.get("/api/tasks/stats/count").json()[0]["total"]) is int
