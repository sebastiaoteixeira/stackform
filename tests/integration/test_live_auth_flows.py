import base64
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest
from fastapi import FastAPI

from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.runtime.dpop import generate_private_key_pem
from yaml_api_generator.server.common.context_builder import build_runtime_context
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.fastapi.factory import register_fastapi_routes
from yaml_api_generator.server.fastapi.server import build_app
from tests.unit.support.repositories import InMemoryRepository


EXAMPLES = Path(__file__).parents[2] / "examples"
pytestmark = pytest.mark.integration


class OIDCProviderHandler(BaseHTTPRequestHandler):
    challenge: str | None = None
    token_requests = 0
    userinfo_requests = 0

    @property
    def origin(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/.well-known/openid-configuration":
            self._json(
                {
                    "authorization_endpoint": f"{self.origin}/authorize",
                    "token_endpoint": f"{self.origin}/token",
                    "userinfo_endpoint": f"{self.origin}/userinfo",
                }
            )
            return
        if parsed.path == "/authorize":
            query = parse_qs(parsed.query)
            type(self).challenge = query["code_challenge"][0]
            location = query["redirect_uri"][0] + "?" + urlencode(
                {
                    "code": "provider-code",
                    "state": query["state"][0],
                }
            )
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()
            return
        if parsed.path == "/userinfo":
            assert self.headers["Authorization"] == "DPoP provider-access-token"
            assert self.headers["DPoP"]
            type(self).userinfo_requests += 1
            self._json(
                {
                    "sub": "external-user-1",
                    "email": "external@example.com",
                    "name": "External User",
                }
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/token":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode())
        verifier = form["code_verifier"][0]
        digest = sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert challenge == type(self).challenge
        assert form["code"] == ["provider-code"]
        assert self.headers["DPoP"]
        type(self).token_requests += 1
        self._json(
            {
                "access_token": "provider-access-token",
                "token_type": "DPoP",
            }
        )

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


@pytest.fixture
def oidc_provider():
    server = ThreadingHTTPServer(("127.0.0.1", 0), OIDCProviderHandler)
    OIDCProviderHandler.challenge = None
    OIDCProviderHandler.token_requests = 0
    OIDCProviderHandler.userinfo_requests = 0
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _runtime_app(spec: Path, repository: InMemoryRepository) -> FastAPI:
    ir = load_and_generate_ir(spec).ir
    context = build_runtime_context(ir)
    repository.register_id_field("users", "id")
    app = FastAPI()
    register_fastapi_routes(app, context, RepositoryRegistry.single(repository))
    return app


@pytest.mark.asyncio
async def test_development_server_password_login_and_role_access(tmp_path):
    source = EXAMPLES / "v03" / "password-role" / "spec.yaml"
    database = tmp_path / "password-role.sqlite"
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        source.read_text().replace(
            "sqlite+aiosqlite:///v03-password-role.sqlite",
            f"sqlite+aiosqlite:///{database}",
        )
    )
    app = build_app(spec)
    configured_paths = {route.path for route in app.routes}
    assert "/api/v1/users/login" in configured_paths

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://app.test"
    ) as client:
        registration = await client.post(
            "/api/v1/users/register",
            json={
                "email": "user@example.com",
                "displayName": "User",
                "password": "secret-password",
            },
        )
        assert registration.status_code == 200
        login = await client.post(
            "/api/v1/users/login",
            json={"email": "user@example.com", "password": "secret-password"},
        )
        assert login.status_code == 200
        token = login.json()["token"]
        protected = await client.get(
            "/api/v1/users", headers={"Authorization": f"Bearer {token}"}
        )

    assert protected.status_code == 200
    assert protected.json()[0]["email"] == "user@example.com"


def test_generated_fastapi_password_login_and_role_access(tmp_path):
    output = tmp_path / "generated"
    compile_project(
        EXAMPLES / "v03" / "password-role" / "spec.yaml",
        output_dir=output,
        target="fastapi",
    )
    backend = output / "backend"
    script = """
import asyncio
import json
import httpx
from app import app

async def main():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://generated.test"
        ) as client:
            registration = await client.post(
                "/api/v1/users/register",
                json={
                    "email": "built@example.com",
                    "displayName": "Built User",
                    "password": "built-secret",
                },
            )
            login = await client.post(
                "/api/v1/users/login",
                json={"email": "built@example.com", "password": "built-secret"},
            )
            token = login.json().get("token", "")
            protected = await client.get(
                "/api/v1/users", headers={"Authorization": f"Bearer {token}"}
            )
            print(json.dumps({
                "registration": registration.status_code,
                "login": login.status_code,
                "protected": protected.status_code,
                "users": protected.json(),
            }))

asyncio.run(main())
"""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(backend), str(Path(__file__).parents[2] / "src"))),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    observed = json.loads(result.stdout)
    assert observed["registration"] == 200
    assert observed["login"] == 200
    assert observed["protected"] == 200
    assert observed["users"][0]["email"] == "built@example.com"
    assert "_auth" not in observed["users"][0]


def test_generated_fastapi_password_login_over_mongo(tmp_path):
    """The Mongo repository must surface the auth material the login route reads.

    No Mongo server is needed: the generated repository is driven over a stub
    collection, which is what pins the normalisation contract the route relies on.
    """
    source = EXAMPLES / "v03" / "password-role" / "spec.yaml"
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        source.read_text().replace(
            "    type: postgres\n    dsn: sqlite+aiosqlite:///v03-password-role.sqlite",
            "    type: mongodb\n    uri: mongodb://localhost:27017\n    database: password_role",
        )
    )
    output = tmp_path / "generated"
    compile_project(spec, output_dir=output, target="fastapi")
    backend = output / "backend"
    script = """
import asyncio
import json

from dependencies.auth import hash_password
from repositories.users import UsersRepository
from routes.login import UsersLoginPayload, login_users


class StubCursor:
    def __init__(self, documents):
        self._documents = documents

    async def to_list(self, length=None):
        return list(self._documents)


class StubCollection:
    def __init__(self, documents):
        self._documents = documents

    def find(self, query):
        return StubCursor(self._documents)

    async def find_one(self, query):
        return next(
            (
                document
                for document in self._documents
                if all(document.get(field) == value for field, value in query.items())
            ),
            None,
        )


async def main():
    stored = {
        "_id": "datastore-identifier",
        "id": "u1",
        "email": "user@example.com",
        "displayName": "User",
        "role": "user",
        "_auth": {"passwordHash": hash_password("secret-password")},
    }
    repository = UsersRepository({"users": StubCollection([stored])})
    session = await login_users(
        UsersLoginPayload(email="user@example.com", password="secret-password"),
        repository=repository,
    )
    read = await repository.list()
    print(json.dumps({"read": sorted(read[0]), "session": session}))

asyncio.run(main())
"""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(backend), str(Path(__file__).parents[2] / "src"))),
        "JWT_SECRET": "regression-secret-of-sufficient-length",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    observed = json.loads(result.stdout)
    assert "_auth" in observed["read"]
    assert "_id" not in observed["read"]
    assert observed["session"]["token"]
    assert set(observed["session"]["user"]) == {"id", "email", "displayName", "role"}


def test_generated_fastapi_declared_role_outranks_managed_store(tmp_path):
    """An identity that declares a role field is authoritative about its own roles.

    The managed store under ``_auth`` holds roles only for identities that declare
    no such field, so it must not shadow a role the specification made writable.
    """
    output = tmp_path / "generated"
    compile_project(
        EXAMPLES / "valid" / "access-control-advanced.yaml",
        output_dir=output,
        target="fastapi",
    )
    backend = output / "backend"
    script = """
import asyncio
import json

from starlette.requests import Request

from dependencies.auth import resolve_principal
from dependencies.jwt_utils import create_jwt_token
from repositories.users import UsersRepository


class StubCursor:
    def __init__(self, documents):
        self._documents = documents

    async def to_list(self, length=None):
        return list(self._documents)


class StubCollection:
    def __init__(self, documents):
        self._documents = documents

    def find(self, query):
        return StubCursor(self._documents)

    async def find_one(self, query):
        return next(
            (
                document
                for document in self._documents
                if all(document.get(field) == value for field, value in query.items())
            ),
            None,
        )


async def main():
    administrator = {
        "_id": "datastore-identifier",
        "id": "u1",
        "email": "admin@example.test",
        "name": "Administrator",
        "role": "admin",
        "_auth": {"passwordHash": "unused", "roles": "viewer"},
    }
    repository = UsersRepository({"users": StubCollection([administrator])})
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/v1/users",
        "headers": [(b"authorization", b"Bearer " + create_jwt_token("u1", "users").encode())],
    })
    principal = await resolve_principal(request, repositories={"users": repository})
    print(json.dumps(principal["roles"]))

asyncio.run(main())
"""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(backend), str(Path(__file__).parents[2] / "src"))),
        "JWT_SECRET": "regression-secret-of-sufficient-length",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == ["admin"]


@pytest.mark.asyncio
async def test_external_oidc_pkce_dpop_flow_over_live_http(oidc_provider, monkeypatch):
    monkeypatch.setenv(
        "OIDC_DISCOVERY_URL",
        f"{oidc_provider}/.well-known/openid-configuration",
    )
    monkeypatch.setenv("IDENTITY_DPOP_PRIVATE_KEY", generate_private_key_pem())
    repository = InMemoryRepository()
    app = _runtime_app(EXAMPLES / "v03" / "oidc-pkce-dpop" / "spec.yaml", repository)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://app.test"
    ) as client:
        login = await client.get("/api/users/auth/identity", follow_redirects=False)
        assert login.status_code in (302, 307)

        async with httpx.AsyncClient() as provider_client:
            authorization = await provider_client.get(
                login.headers["location"], follow_redirects=False
            )
        assert authorization.status_code == 302

        callback = await client.get(
            authorization.headers["location"], follow_redirects=False
        )
        assert callback.status_code in (302, 307)
        login_code = parse_qs(urlparse(callback.headers["location"]).query)["code"][0]

        exchange = await client.post("/api/auth/exchange", json={"code": login_code})

    assert exchange.status_code == 200
    assert exchange.json()["token"]
    assert OIDCProviderHandler.token_requests == 1
    assert OIDCProviderHandler.userinfo_requests == 1
    assert repository.documents("users")[0]["email"] == "external@example.com"
