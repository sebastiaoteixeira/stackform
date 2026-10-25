import asyncio
import re
import time
import types
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jinja2 import Environment, FileSystemLoader

from yaml_api_generator.generators.backend.compile_context import (
    AuthConfig,
    IdentityCollectionDescriptor,
    IdpProviderDescriptor,
    ProviderBindingDescriptor,
)
from yaml_api_generator.generators.backend.fastapi import access_filters
from yaml_api_generator.server.common.steps.authorization import _principal_has_role
from yaml_api_generator.ir import IRProviderBinding
from yaml_api_generator.runtime.access import role_names
from yaml_api_generator.ir.api import IROIDCProvider
from yaml_api_generator.server.common.auth import idp
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.common.server_context import (
    RuntimeCollectionDescriptor,
    RuntimeIdentityDescriptor,
)
from yaml_api_generator.server.common.steps.authentication import _resolve_idp_principal
from yaml_api_generator.server.common.utils.field_access import resolve_claim_path
from yaml_api_generator.utils.strings import to_py_identifier
from tests.unit.support.repositories import InMemoryRepository

_ISSUER = "https://kc.example.com/realms/main"
_CLIENT_ID = "my-app"
_DISCOVERY = "http://localhost:8080/.well-known/openid-configuration"
_ROLES_CLAIM = "realm_access.roles"
_LOCAL_ROLES_FIELD = "orgRole"

_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "yaml_api_generator" / "generators" / "backend" / "fastapi" / "templates"
)


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _patch_jwks(rsa_key, monkeypatch):
    async def fake_discovery(_url):
        return {"jwks_uri": "https://kc.example.com/jwks", "issuer": _ISSUER}

    async def fake_signing_key(_jwks_uri, _kid):
        class _Key:
            key = rsa_key.public_key()
        return _Key()

    monkeypatch.setattr(idp, "_discovery", fake_discovery)
    monkeypatch.setattr(idp, "_get_signing_key", fake_signing_key)


def _sign(rsa_key, **claims):
    payload = {"iss": _ISSUER, "aud": _CLIENT_ID, "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, rsa_key, algorithm="RS256")


def _provider():
    return IROIDCProvider(
        name="keycloak",
        client_id=_CLIENT_ID,
        trust="idp",
        discovery_url=_DISCOVERY,
        issuer=_ISSUER,
        audiences=(_CLIENT_ID,),
    )


class TestDevRolesFromClaims:
    def _resolve(self, rsa_key, **extra_claims):
        identity = RuntimeIdentityDescriptor(
            name="users",
            bindings=(IRProviderBinding(
                provider="keycloak",
                identifier="email",
                claim_mapping={"email": "email", _LOCAL_ROLES_FIELD: _ROLES_CLAIM},
                auto_provision=True,
            ),),
            id_field="id",
            roles_field=_LOCAL_ROLES_FIELD,
        )
        collection = RuntimeCollectionDescriptor(
            name="users", type="auth", id_field="id", id_format="uuidv7", fields={}
        )
        repo = InMemoryRepository({
            "users": [{"id": "kc-sub", "email": "a@x.com", _LOCAL_ROLES_FIELD: "stale"}]
        })
        repo.register_id_field("users", "id")
        registry = RepositoryRegistry(
            repositories={"m": repo}, bindings={"users": "m"}, default="m"
        )
        token = _sign(rsa_key, sub="kc-sub", email="a@x.com", **extra_claims)
        return asyncio.run(_resolve_idp_principal(
            token,
            {"users": identity},
            {"users": collection},
            {"keycloak": _provider()},
            registry,
        ))

    def test_roles_populated_from_mapped_claim_path(self, rsa_key):
        principal = self._resolve(rsa_key, realm_access={"roles": ["admin", "user"]})
        assert principal["roles"] == ["admin", "user"]

    def test_roles_not_read_from_local_field_name(self, rsa_key):
        principal = self._resolve(rsa_key, orgRole=["wrong"], realm_access={"roles": ["editor"]})
        assert principal["roles"] == ["editor"]

    def test_role_grant_after_claim_mapping(self, rsa_key):
        principal = self._resolve(rsa_key, realm_access={"roles": ["admin"]})
        assert _principal_has_role(principal, "admin", None) is True
        assert _principal_has_role(principal, "superuser", None) is False


def _render_auth_py(roles_field, claim_mapping):
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), keep_trailing_newline=True)
    env.filters["py_literal"] = access_filters.py_literal
    env.filters["py_identifier"] = to_py_identifier
    provider = _provider()
    binding = ProviderBindingDescriptor(
        provider="keycloak",
        identifier="email",
        claim_mapping=claim_mapping,
        auto_provision=True,
        relations=[],
    )
    identity = IdentityCollectionDescriptor(
        name="users",
        bindings=[binding],
        id_field="id",
        roles=None,
        roles_field=roles_field,
        issues_jwt=False,
        datastore_type="mongodb",
        id_format="uuidv7",
    )
    auth = AuthConfig(
        enabled=True,
        identity_collections=[identity],
        has_password_auth=False,
        has_api_key_auth=False,
        has_oidc_auth=True,
        has_idp_auth=True,
        has_app_oidc_auth=False,
        idp_providers=[IdpProviderDescriptor(
            name="keycloak",
            discovery_url=_DISCOVERY,
            client_id=_CLIENT_ID,
            issuer=_ISSUER,
            audiences=(_CLIENT_ID,),
        )],
        providers={"keycloak": provider},
    )
    return env.get_template("auth.py.jinja").render(auth=auth)


def _exec_roles_from_claims(source):
    fragment = source[source.index("def _roles_from_claims"):]
    fragment = fragment[:fragment.index("\n\n")]
    module = types.ModuleType("auth_fragment")
    module.__dict__.update({"resolve_claim_path": resolve_claim_path, "role_names": role_names, "Any": object})
    exec(compile(fragment, "<auth>", "exec"), module.__dict__)
    return module._roles_from_claims


class TestEmittedRolesFromClaims:
    def test_emitted_roles_claim_path_is_mapped_claim_not_local_name(self):
        source = _render_auth_py(_LOCAL_ROLES_FIELD, {"email": "email", _LOCAL_ROLES_FIELD: _ROLES_CLAIM})
        match = re.search(r"_roles_claim_path = (.+)", source)
        assert match is not None
        assert match.group(1).strip() == repr(_ROLES_CLAIM)
        assert "'orgRole'" not in match.group(1)

    def test_emitted_roles_from_claims_resolves_dotted_path(self):
        source = _render_auth_py(_LOCAL_ROLES_FIELD, {"email": "email", _LOCAL_ROLES_FIELD: _ROLES_CLAIM})
        fn = _exec_roles_from_claims(source)
        assert fn({"realm_access": {"roles": ["admin", "user"]}}, _ROLES_CLAIM) == ["admin", "user"]

    def test_emitted_roles_use_mapped_path_when_local_key_absent(self):
        source = _render_auth_py(_LOCAL_ROLES_FIELD, {"email": "email", _LOCAL_ROLES_FIELD: _ROLES_CLAIM})
        match = re.search(r"_roles_claim_path = (.+)", source)
        emitted_path = eval(match.group(1).strip())
        fn = _exec_roles_from_claims(source)
        claims = {"realm_access": {"roles": ["editor"]}}
        assert _LOCAL_ROLES_FIELD not in claims
        assert fn(claims, emitted_path) == ["editor"]
