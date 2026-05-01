import pytest

from yaml_api_generator.server.auth.jwt import decode_jwt_token
from yaml_api_generator.server.auth.password import hash_password
from yaml_api_generator.server.request_context import RequestContext
from yaml_api_generator.server.repositories.base import BaseRepository
from yaml_api_generator.server.server_context import RuntimeIdentityDescriptor
from yaml_api_generator.server.steps.authorization import UnauthorizedError
from yaml_api_generator.server.steps.login import LoginStep
from .test_repository_steps import InMemoryRepository, _make_ctx


def _make_identity() -> RuntimeIdentityDescriptor:
    return RuntimeIdentityDescriptor(
        name="users",
        identifier="email",
        via=["password"],
        id_field="id",
    )


def _seed_user(repo: InMemoryRepository, email="a@b.com", password="secret123") -> dict:
    hashed = hash_password(password)
    user = {
        "id": "user-1",
        "email": email,
        "displayName": "Test",
        "_auth": {"passwordHash": hashed},
    }
    repo._data.setdefault("users", {})["user-1"] = user
    return user


@pytest.mark.asyncio
async def test_login_valid_credentials():
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    _seed_user(repo)
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(
        repository=repo,
        collection="users",
        operation="login",
        body={"email": "a@b.com", "password": "secret123"},
    )
    result = await step(ctx)
    assert "token" in result.response
    assert "user" in result.response
    assert result.response["user"]["email"] == "a@b.com"


@pytest.mark.asyncio
async def test_login_non_dict_body():
    repo = InMemoryRepository()
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(repository=repo, body="not a dict")
    with pytest.raises(UnauthorizedError):
        await step(ctx)


@pytest.mark.asyncio
async def test_login_missing_identifier():
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    _seed_user(repo)
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(repository=repo, body={"password": "secret123"})
    with pytest.raises(UnauthorizedError):
        await step(ctx)


@pytest.mark.asyncio
async def test_login_missing_password():
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    _seed_user(repo)
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(repository=repo, body={"email": "a@b.com"})
    with pytest.raises(UnauthorizedError):
        await step(ctx)


@pytest.mark.asyncio
async def test_login_wrong_password():
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    _seed_user(repo)
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(
        repository=repo,
        body={"email": "a@b.com", "password": "wrong"},
    )
    with pytest.raises(UnauthorizedError):
        await step(ctx)


@pytest.mark.asyncio
async def test_login_user_not_found():
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(
        repository=repo,
        body={"email": "nobody@nowhere.com", "password": "secret123"},
    )
    with pytest.raises(UnauthorizedError):
        await step(ctx)


@pytest.mark.asyncio
async def test_login_user_missing_id_field():
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    hashed = hash_password("secret123")
    user = {"email": "a@b.com", "_auth": {"passwordHash": hashed}}
    repo._data.setdefault("users", {})["no-id"] = user
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(
        repository=repo,
        body={"email": "a@b.com", "password": "secret123"},
    )
    with pytest.raises(UnauthorizedError):
        await step(ctx)


@pytest.mark.asyncio
async def test_login_safe_user_strips_password_id_auth():
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    _seed_user(repo)
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(
        repository=repo,
        body={"email": "a@b.com", "password": "secret123"},
    )
    result = await step(ctx)
    user = result.response["user"]
    assert "password" not in user
    assert "_id" not in user
    assert "_auth" not in user


@pytest.mark.asyncio
async def test_login_jwt_token_contains_sub_and_identity_collection():
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    _seed_user(repo)
    identity = _make_identity()
    step = LoginStep(identity, "id", repo)
    ctx = _make_ctx(
        repository=repo,
        body={"email": "a@b.com", "password": "secret123"},
    )
    result = await step(ctx)
    claims = decode_jwt_token(result.response["token"])
    assert claims is not None
    assert claims["sub"] == "user-1"
    assert claims["identity_collection"] == "users"
