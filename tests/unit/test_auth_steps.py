import base64
from typing import Any

import pytest

from yaml_api_generator.ir import IRProviderBinding
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.server_context import (
    RuntimeAccessRule,
    RuntimeAuthConfig,
    RuntimeIdentityDescriptor,
)
from yaml_api_generator.server.common.steps.authentication import ResolvePrincipalStep
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.common.auth.utils import (
    extract_api_key,
    extract_basic_credentials,
    extract_bearer_token,
)
from yaml_api_generator.server.common.steps.authorization import (
    AuthorizeRouteStep,
    ForbiddenError,
    PostFetchAuthorizeStep,
    UnauthorizedError,
    ValidateIdentityCreateStep,
)
from yaml_api_generator.ir.when import (
    Equals,
    FieldRef,
    NotEquals,
    StringLiteral,
)
from yaml_api_generator.server.common.auth.password import hash_password
from yaml_api_generator.server.common.repositories.base import BaseRepository


class InMemoryRepository(BaseRepository):
    def __init__(self, data: dict[str, list[dict[str, Any]]] | None = None):
        self._data: dict[str, list[dict[str, Any]]] = data or {}

    def connect(self):
        pass

    async def close(self):
        pass

    async def list(self, collection_name: str) -> list[dict[str, Any]]:
        return list(self._data.get(collection_name, []))

    async def get(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        for doc in self._data.get(collection_name, []):
            if doc.get("id") == document_id:
                return doc
        return None

    async def create(
        self, collection_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._data.setdefault(collection_name, []).append(payload)
        return payload

    async def update(
        self, collection_name: str, document_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return None

    async def replace(
        self, collection_name: str, document_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return None

    async def delete(
        self, collection_name: str, document_id: str
    ) -> dict[str, Any] | None:
        return None


def _make_ctx(**overrides) -> RequestContext:
    defaults = dict(
        method="GET",
        path="/users",
        api_version=None,
        collection="users",
        operation="list",
        headers={},
        url_params={},
        repository=None,
        principal=None,
        body=None,
        response=None,
    )
    defaults.update(overrides)
    return RequestContext(**defaults)


def _basic_header(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _make_identity(
    name: str = "users",
    identifier: str | None = "email",
    via: list[str] | None = None,
    id_field: str = "id",
    roles_field: str | None = "role",
) -> RuntimeIdentityDescriptor:
    providers = via or ["password"]
    bindings = tuple(
        IRProviderBinding(provider=p, identifier=identifier or "")
        for p in providers
    )
    return RuntimeIdentityDescriptor(
        name=name,
        bindings=bindings,
        id_field=id_field,
        roles_field=roles_field,
    )


class TestExtractBearerToken:
    def test_189_bearer_token_from_header(self):
        result = extract_bearer_token({"Authorization": "Bearer mytoken123"})
        assert result == "mytoken123"

    def test_190_no_authorization_header(self):
        result = extract_bearer_token({})
        assert result is None

    def test_191_basic_auth_not_extracted_as_bearer(self):
        result = extract_bearer_token({"Authorization": "Basic abc123"})
        assert result is None


class TestExtractApiKey:
    def test_192_api_key_from_header(self):
        result = extract_api_key({"X-API-Key": "myapikey"})
        assert result == "myapikey"

    def test_193_api_key_falls_back_to_bearer(self):
        result = extract_api_key({"Authorization": "Bearer mytoken"})
        assert result == "mytoken"

    def test_194_x_api_key_takes_priority_over_bearer(self):
        result = extract_api_key(
            {
                "X-API-Key": "key123",
                "Authorization": "Bearer token456",
            }
        )
        assert result == "key123"


class TestExtractBasicCredentials:
    def test_195_basic_credentials_valid(self):
        result = extract_basic_credentials(
            {"Authorization": _basic_header("user", "pass")}
        )
        assert result == ("user", "pass")

    def test_196_basic_bad_base64(self):
        with pytest.raises(UnauthorizedError):
            extract_basic_credentials({"Authorization": "Basic !!!notbase64!!!"})

    def test_197_basic_missing_colon(self):
        encoded = base64.b64encode(b"nocolonhere").decode("ascii")
        with pytest.raises(UnauthorizedError):
            extract_basic_credentials({"Authorization": f"Basic {encoded}"})

    def test_198_basic_empty_username(self):
        encoded = base64.b64encode(b":pass").decode("ascii")
        with pytest.raises(UnauthorizedError):
            extract_basic_credentials({"Authorization": f"Basic {encoded}"})

    def test_199_basic_empty_password(self):
        encoded = base64.b64encode(b"user:").decode("ascii")
        with pytest.raises(UnauthorizedError):
            extract_basic_credentials({"Authorization": f"Basic {encoded}"})

    def test_200_basic_password_containing_colon(self):
        encoded = base64.b64encode(b"user:pass:with:colons").decode("ascii")
        result = extract_basic_credentials({"Authorization": f"Basic {encoded}"})
        assert result == ("user", "pass:with:colons")


class TestResolvePrincipalStep:
    @pytest.mark.asyncio
    async def test_201_password_auth_resolves_principal(self):
        pw_hash = hash_password("secret")
        repo = InMemoryRepository(
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "a@b.com",
                        "role": "admin",
                        "_auth": {"passwordHash": pw_hash},
                    }
                ]
            }
        )
        identity = _make_identity(name="users", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": _basic_header("a@b.com", "secret")})
        result = await step(ctx)
        assert result.principal is not None
        assert result.principal["sub"] == "u1"
        assert result.principal["identity_collection"] == "users"

    @pytest.mark.asyncio
    async def test_202_password_auth_wrong_password_no_principal(self):
        pw_hash = hash_password("secret")
        repo = InMemoryRepository(
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "a@b.com",
                        "_auth": {"passwordHash": pw_hash},
                    }
                ]
            }
        )
        identity = _make_identity(name="users", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": _basic_header("a@b.com", "wrong")})
        result = await step(ctx)
        assert result.principal is None

    @pytest.mark.asyncio
    async def test_203_password_auth_wrong_identifier_no_principal(self):
        pw_hash = hash_password("secret")
        repo = InMemoryRepository(
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "a@b.com",
                        "_auth": {"passwordHash": pw_hash},
                    }
                ]
            }
        )
        identity = _make_identity(name="users", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(
            headers={"Authorization": _basic_header("other@b.com", "secret")}
        )
        result = await step(ctx)
        assert result.principal is None

    @pytest.mark.asyncio
    async def test_204_api_key_auth_resolves_principal(self):
        repo = InMemoryRepository(
            {
                "clients": [
                    {
                        "id": "c1",
                        "clientId": "myclient",
                        "_auth": {"apiKey": "ak123"},
                    }
                ]
            }
        )
        identity = _make_identity(
            name="clients",
            identifier="clientId",
            via=["apiKey"],
            id_field="id",
        )
        step = ResolvePrincipalStep(
            identity_collections={"clients": identity},
            identity_id_fields={"clients": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"X-API-Key": "ak123"})
        result = await step(ctx)
        assert result.principal is not None
        assert result.principal["sub"] == "c1"
        assert result.principal["identity_collection"] == "clients"

    @pytest.mark.asyncio
    async def test_205_api_key_wrong_key_no_principal(self):
        repo = InMemoryRepository(
            {
                "clients": [
                    {
                        "id": "c1",
                        "clientId": "myclient",
                        "_auth": {"apiKey": "ak123"},
                    }
                ]
            }
        )
        identity = _make_identity(name="clients", via=["apiKey"])
        step = ResolvePrincipalStep(
            identity_collections={"clients": identity},
            identity_id_fields={"clients": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"X-API-Key": "wrong"})
        result = await step(ctx)
        assert result.principal is None

    @pytest.mark.asyncio
    async def test_206_no_credentials_no_principal(self):
        repo = InMemoryRepository()
        identity = _make_identity(name="users", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={})
        result = await step(ctx)
        assert result.principal is None

    @pytest.mark.asyncio
    async def test_207_principal_record_excludes_auth_fields(self):
        pw_hash = hash_password("secret")
        repo = InMemoryRepository(
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "a@b.com",
                        "displayName": "Alice",
                        "_auth": {"passwordHash": pw_hash},
                    }
                ]
            }
        )
        identity = _make_identity(name="users", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": _basic_header("a@b.com", "secret")})
        result = await step(ctx)
        assert result.principal is not None
        assert "_auth" not in result.principal["record"]
        assert "password" not in result.principal["record"]

    @pytest.mark.asyncio
    async def test_208_principal_roles_from_roles_field(self):
        pw_hash = hash_password("secret")
        repo = InMemoryRepository(
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "a@b.com",
                        "role": "admin",
                        "_auth": {"passwordHash": pw_hash},
                    }
                ]
            }
        )
        identity = _make_identity(name="users", via=["password"], roles_field="role")
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": _basic_header("a@b.com", "secret")})
        result = await step(ctx)
        assert result.principal is not None
        assert "admin" in result.principal["roles"]

    @pytest.mark.asyncio
    async def test_209_multiple_identity_collections_first_match(self):
        pw_hash = hash_password("secret")
        repo = InMemoryRepository(
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "a@b.com",
                        "role": "user",
                        "_auth": {"passwordHash": pw_hash},
                    }
                ],
                "admins": [
                    {
                        "id": "a1",
                        "email": "admin@b.com",
                        "role": "superadmin",
                        "_auth": {"passwordHash": hash_password("adminpw")},
                    }
                ],
            }
        )
        user_identity = _make_identity(name="users", via=["password"])
        admin_identity = _make_identity(name="admins", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": user_identity, "admins": admin_identity},
            identity_id_fields={"users": "id", "admins": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": _basic_header("a@b.com", "secret")})
        result = await step(ctx)
        assert result.principal is not None
        assert result.principal["identity_collection"] == "users"

    @pytest.mark.asyncio
    async def test_210_bearer_jwt_resolves_principal(self):
        from yaml_api_generator.server.common.auth.jwt import create_jwt_token

        pw_hash = hash_password("secret")
        repo = InMemoryRepository(
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "a@b.com",
                        "role": "admin",
                        "_auth": {"passwordHash": pw_hash},
                    }
                ]
            }
        )
        identity = _make_identity(name="users", via=["password"])
        token = create_jwt_token("u1", "users")
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": f"Bearer {token}"})
        result = await step(ctx)
        assert result.principal is not None
        assert result.principal["sub"] == "u1"

    @pytest.mark.asyncio
    async def test_211_bearer_invalid_jwt_no_principal(self):
        repo = InMemoryRepository()
        identity = _make_identity(name="users", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": "Bearer invalid.token.here"})
        result = await step(ctx)
        assert result.principal is None

    @pytest.mark.asyncio
    async def test_212_empty_collection_no_principal(self):
        repo = InMemoryRepository({"users": []})
        identity = _make_identity(name="users", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": _basic_header("a@b.com", "secret")})
        result = await step(ctx)
        assert result.principal is None

    @pytest.mark.asyncio
    async def test_213_api_key_via_bearer_fallback(self):
        repo = InMemoryRepository(
            {
                "clients": [
                    {
                        "id": "c1",
                        "_auth": {"apiKey": "ak123"},
                    }
                ]
            }
        )
        identity = _make_identity(name="clients", identifier=None, via=["apiKey"])
        step = ResolvePrincipalStep(
            identity_collections={"clients": identity},
            identity_id_fields={"clients": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": "Bearer ak123"})
        result = await step(ctx)
        assert result.principal is not None
        assert result.principal["sub"] == "c1"

    @pytest.mark.asyncio
    async def test_214_principal_sub_is_string(self):
        pw_hash = hash_password("secret")
        repo = InMemoryRepository(
            {
                "users": [
                    {
                        "id": "u1",
                        "email": "a@b.com",
                        "_auth": {"passwordHash": pw_hash},
                    }
                ]
            }
        )
        identity = _make_identity(name="users", via=["password"])
        step = ResolvePrincipalStep(
            identity_collections={"users": identity},
            identity_id_fields={"users": "id"},
            registry=RepositoryRegistry.single(repo),
        )
        ctx = _make_ctx(headers={"Authorization": _basic_header("a@b.com", "secret")})
        result = await step(ctx)
        assert isinstance(result.principal["sub"], str)


class TestValidateIdentityCreateStep:
    @staticmethod
    def _make_step(
        name: str = "users",
        identifier: str | None = "email",
        via: list[str] | None = None,
    ) -> "Step":
        identity = _make_identity(
            name=name, identifier=identifier, via=via or ["password"]
        )
        return ValidateIdentityCreateStep(identity)

    def test_215_valid_body_with_all_fields(self):
        step = self._make_step()
        ctx = _make_ctx(
            collection="users",
            operation="create",
            body={"email": "a@b.com", "password": "secret123"},
        )
        result = step(ctx)
        assert result is ctx

    def test_216_missing_identifier_field(self):
        step = self._make_step()
        ctx = _make_ctx(
            collection="users",
            operation="create",
            body={"password": "secret123"},
        )
        with pytest.raises(ValueError, match="Missing required fields"):
            step(ctx)

    def test_217_missing_password_field(self):
        step = self._make_step()
        ctx = _make_ctx(
            collection="users",
            operation="create",
            body={"email": "a@b.com"},
        )
        with pytest.raises(ValueError, match="Missing required fields"):
            step(ctx)

    def test_218_empty_string_identifier(self):
        step = self._make_step()
        ctx = _make_ctx(
            collection="users",
            operation="create",
            body={"email": "  ", "password": "secret123"},
        )
        with pytest.raises(ValueError, match="Missing required fields"):
            step(ctx)

    def test_219_empty_string_password(self):
        step = self._make_step()
        ctx = _make_ctx(
            collection="users",
            operation="create",
            body={"email": "a@b.com", "password": "  "},
        )
        with pytest.raises(ValueError, match="Missing required fields"):
            step(ctx)

    def test_220_non_create_operation_passes_through(self):
        step = self._make_step()
        ctx = _make_ctx(
            collection="users",
            operation="list",
            body={},
        )
        result = step(ctx)
        assert result is ctx

    def test_221_different_collection_passes_through(self):
        step = self._make_step(name="users")
        ctx = _make_ctx(
            collection="posts",
            operation="create",
            body={"title": "hello"},
        )
        result = step(ctx)
        assert result is ctx


class TestAuthorizeRouteStep:
    def test_222_no_principal_raises_unauthorized(self):
        step = AuthorizeRouteStep()
        ctx = _make_ctx(principal=None)
        with pytest.raises(UnauthorizedError):
            step(ctx)

    def test_223_no_rules_with_principal_passes(self):
        step = AuthorizeRouteStep()
        ctx = _make_ctx(
            principal={"sub": "u1", "identity_collection": "users", "record": {}}
        )
        result = step(ctx)
        assert result is ctx

    def test_224_matching_allow_rule(self):
        rules = [RuntimeAccessRule(principal="identity:users")]
        step = AuthorizeRouteStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            }
        )
        result = step(ctx)
        assert result is ctx

    def test_225_non_matching_collection_forbidden(self):
        rules = [RuntimeAccessRule(principal="identity:admins")]
        step = AuthorizeRouteStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            }
        )
        with pytest.raises(ForbiddenError):
            step(ctx)

    def test_226_deny_rule_raises_forbidden(self):
        rules = [RuntimeAccessRule(principal="identity:users", effect="deny")]
        step = AuthorizeRouteStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            }
        )
        with pytest.raises(ForbiddenError):
            step(ctx)

    def test_227_rule_with_role_check(self):
        rules = [RuntimeAccessRule(principal="identity:users", required_role="admin")]
        step = AuthorizeRouteStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
                "roles": ["admin"],
            }
        )
        result = step(ctx)
        assert result is ctx

    def test_228_rule_with_role_missing(self):
        rules = [RuntimeAccessRule(principal="identity:users", required_role="admin")]
        step = AuthorizeRouteStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
                "roles": ["user"],
            }
        )
        with pytest.raises(ForbiddenError):
            step(ctx)

    def test_229_when_expression_matches(self):
        when = Equals(
            FieldRef("principal", ("sub",)),
            StringLiteral("u1"),
        )
        rules = [RuntimeAccessRule(principal="identity:users", when=when)]
        step = AuthorizeRouteStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            }
        )
        result = step(ctx)
        assert result is ctx

    def test_230_when_expression_no_match(self):
        when = Equals(
            FieldRef("principal", ("sub",)),
            StringLiteral("other"),
        )
        rules = [RuntimeAccessRule(principal="identity:users", when=when)]
        step = AuthorizeRouteStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            }
        )
        with pytest.raises(ForbiddenError):
            step(ctx)

    def test_231_document_needing_rule_defers(self):
        when = Equals(
            FieldRef("document", ("authorId",)),
            FieldRef("principal", ("sub",)),
        )
        rules = [RuntimeAccessRule(principal="identity:users", when=when)]
        step = AuthorizeRouteStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            }
        )
        result = step(ctx)
        assert result is ctx


class TestPostFetchAuthorizeStep:
    def test_232_document_match_allows(self):
        when = Equals(
            FieldRef("document", ("authorId",)),
            FieldRef("principal", ("sub",)),
        )
        rules = [RuntimeAccessRule(principal="identity:users", when=when)]
        step = PostFetchAuthorizeStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            },
            response={"id": "p1", "authorId": "u1"},
        )
        result = step(ctx)
        assert result is ctx

    def test_233_document_no_match_forbidden(self):
        when = Equals(
            FieldRef("document", ("authorId",)),
            FieldRef("principal", ("sub",)),
        )
        rules = [RuntimeAccessRule(principal="identity:users", when=when)]
        step = PostFetchAuthorizeStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            },
            response={"id": "p1", "authorId": "u2"},
        )
        with pytest.raises(ForbiddenError):
            step(ctx)

    def test_234_no_response_passes(self):
        rules = [RuntimeAccessRule(principal="identity:users")]
        step = PostFetchAuthorizeStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            },
            response=None,
        )
        result = step(ctx)
        assert result is ctx

    def test_235_deny_rule_with_document(self):
        when = Equals(
            FieldRef("document", ("authorId",)),
            FieldRef("principal", ("sub",)),
        )
        rules = [
            RuntimeAccessRule(principal="identity:users", when=when, effect="deny")
        ]
        step = PostFetchAuthorizeStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            },
            response={"id": "p1", "authorId": "u1"},
        )
        with pytest.raises(ForbiddenError):
            step(ctx)

    def test_236_not_equals_expression(self):
        when = NotEquals(
            FieldRef("document", ("authorId",)),
            FieldRef("principal", ("sub",)),
        )
        rules = [RuntimeAccessRule(principal="identity:users", when=when)]
        step = PostFetchAuthorizeStep(access_rules=rules)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
            },
            response={"id": "p1", "authorId": "u2"},
        )
        result = step(ctx)
        assert result is ctx


class TestRoleHierarchy:
    def _make_auth_config(
        self, hierarchies: dict[str, dict[str, set[str]]]
    ) -> RuntimeAuthConfig:
        return RuntimeAuthConfig(
            enabled=True,
            identity_collections={},
            identity_id_fields={},
            has_password_auth=True,
            has_api_key_auth=False,
            role_hierarchies=hierarchies,
        )

    def test_237_admin_includes_moderator_role(self):
        auth_config = self._make_auth_config(
            {
                "users": {"admin": {"moderator", "user"}, "moderator": {"user"}},
            }
        )
        rules = [
            RuntimeAccessRule(principal="identity:users", required_role="moderator")
        ]
        step = AuthorizeRouteStep(access_rules=rules, auth_config=auth_config)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
                "roles": ["admin"],
            }
        )
        result = step(ctx)
        assert result is ctx

    def test_238_moderator_does_not_include_admin(self):
        auth_config = self._make_auth_config(
            {
                "users": {"admin": {"moderator", "user"}, "moderator": {"user"}},
            }
        )
        rules = [RuntimeAccessRule(principal="identity:users", required_role="admin")]
        step = AuthorizeRouteStep(access_rules=rules, auth_config=auth_config)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
                "roles": ["moderator"],
            }
        )
        with pytest.raises(ForbiddenError):
            step(ctx)

    def test_239_direct_role_still_works_with_hierarchy(self):
        auth_config = self._make_auth_config(
            {
                "users": {"admin": {"moderator"}},
            }
        )
        rules = [
            RuntimeAccessRule(principal="identity:users", required_role="moderator")
        ]
        step = AuthorizeRouteStep(access_rules=rules, auth_config=auth_config)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
                "roles": ["moderator"],
            }
        )
        result = step(ctx)
        assert result is ctx

    def test_240_transitive_role_inclusion(self):
        auth_config = self._make_auth_config(
            {
                "users": {"admin": {"moderator"}, "moderator": {"user"}},
            }
        )
        rules = [RuntimeAccessRule(principal="identity:users", required_role="user")]
        step = AuthorizeRouteStep(access_rules=rules, auth_config=auth_config)
        ctx = _make_ctx(
            principal={
                "sub": "u1",
                "identity_collection": "users",
                "record": {},
                "roles": ["admin"],
            }
        )
        with pytest.raises(ForbiddenError):
            step(ctx)
