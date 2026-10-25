"""The access-control example over real HTTP, in the dev server and the generated FastAPI app."""

import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest

from tests.unit.support.live_apps import SERVERS, serve, write_spec

EXAMPLE = Path(__file__).parents[2] / "examples" / "v03" / "access-control" / "spec.yaml"

# The example's own datastore block, made replaceable by the store a test serves it on
SPEC = re.sub(r"^mongo:\n(?:  .*\n)+", "{datastore}\n", EXAMPLE.read_text(), flags=re.MULTILINE)

ADMIN, ANN, BOB = "admin@x.io", "ann@x.io", "bob@x.io"


def register(client, promote: Callable[[str], None]) -> dict[str, tuple[tuple[str, str], str]]:
    """``ADMIN``, ``ANN`` and ``BOB`` as ``{email: (basic auth, user id)}``, ``ADMIN`` raised to admin in the store."""
    def account(email):
        user = client.post("/api/v1/users/register", json={"email": email, "name": email, "password": "pw"})
        assert user.status_code == 200, user.text
        return (email, "pw"), user.json()["id"]

    accounts = {email: account(email) for email in (ADMIN, ANN, BOB)}
    promote(ADMIN)
    return accounts


def _promote_in_sqlite(store: Path, email: str) -> None:
    with closing(sqlite3.connect(store)) as db, db:
        db.execute("UPDATE users SET _auth = json_set(_auth, '$.roles', json('[\"admin\"]')) WHERE email = ?", (email,))


@pytest.fixture(scope="module", params=SERVERS, ids=lambda server: server.name)
def served(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp(request.param.name)
    with serve(request.param, write_spec(directory, SPEC)) as client:
        yield client, register(client, lambda email: _promote_in_sqlite(directory / "store.sqlite", email))


@pytest.fixture(scope="module")
def client(served):
    return served[0]


@pytest.fixture(scope="module")
def accounts(served):
    return served[1]


def test_anonymous_callers_cannot_delete_users(client, accounts):
    _, ann_id = accounts[ANN]

    assert client.delete(f"/api/v1/users/{ann_id}").status_code == 401


def test_only_admins_delete_users(client, accounts):
    bob, _ = accounts[BOB]
    admin, _ = accounts[ADMIN]
    _, ann_id = accounts[ANN]

    assert client.delete(f"/api/v1/users/{ann_id}", auth=bob).status_code == 403
    assert client.get(f"/api/v1/users/{ann_id}", auth=admin).status_code == 200


OWNED = pytest.mark.parametrize(
    ("path", "owner", "body"),
    [("/api/v1/articles", "author_id", {"title": "t", "content": "c"}), ("/api/v1/sensitive", "owner_id", {"title": "t"})],
    ids=["article", "sensitive"],
)


@OWNED
def test_the_owner_is_bound_to_the_caller(client, accounts, path, owner, body):
    ann, ann_id = accounts[ANN]

    created = client.post(path, json=body, auth=ann)

    assert created.status_code == 200, created.text
    assert client.get(f"{path}/{created.json()['id']}", auth=ann).json()[owner] == ann_id


@OWNED
def test_a_client_cannot_name_the_owner(client, accounts, path, owner, body):
    ann, _ = accounts[ANN]

    assert client.post(path, json={**body, owner: "forged"}, auth=ann).status_code == 422


def test_an_update_cannot_reassign_the_author(client, accounts):
    ann, _ = accounts[ANN]
    created = client.post("/api/v1/articles", json={"title": "t", "content": "c"}, auth=ann).json()

    assert client.patch(f"/api/v1/articles/{created['id']}", json={"author_id": "forged"}, auth=ann).status_code == 422


def test_anonymous_callers_cannot_create_articles(client):
    assert client.post("/api/v1/articles", json={"title": "t", "content": "c"}).status_code == 401


def test_the_sensitive_list_holds_only_the_callers_rows(client, accounts):
    ann, ann_id = accounts[ANN]
    bob, _ = accounts[BOB]
    client.post("/api/v1/sensitive", json={"title": "a", "confidential_info": "ann secret"}, auth=ann)
    client.post("/api/v1/sensitive", json={"title": "b", "confidential_info": "bob secret"}, auth=bob)

    rows = client.get("/api/v1/sensitive", auth=ann).json()

    assert rows and {row["owner_id"] for row in rows} == {ann_id}


def test_admins_list_every_sensitive_row(client, accounts):
    admin, _ = accounts[ADMIN]
    ann, ann_id = accounts[ANN]
    bob, bob_id = accounts[BOB]
    client.post("/api/v1/sensitive", json={"title": "a"}, auth=ann)
    client.post("/api/v1/sensitive", json={"title": "b"}, auth=bob)

    assert {row["owner_id"] for row in client.get("/api/v1/sensitive", auth=admin).json()} >= {ann_id, bob_id}
