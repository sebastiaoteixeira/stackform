import base64
from typing import Any

from yaml_api_generator.ir.api import IROIDCProvider, IRProviderBinding
from yaml_api_generator.runtime.claims import resolve_claim_path
from ..auth import idp, provisioning, verify_password
from ..auth.jwt import SessionTokens
from ..auth.utils import extract_bearer_token, extract_api_key, extract_basic_credentials
from ..request_context import RequestContext
from ..server_context import RuntimeCollectionDescriptor, RuntimeIdentityDescriptor
from ..repositories import BaseRepository, RepositoryRegistry
from ..utils.field_access import get_nested_field
from ..utils.document_matcher import find_document_with_password
from . import Step
from .authorization import UnauthorizedError


def ResolvePrincipalStep(
    identity_collections: dict[str, RuntimeIdentityDescriptor],
    identity_id_fields: dict[str, str],
    registry: RepositoryRegistry,
    providers: dict[str, Any] | None = None,
    collections: dict[str, RuntimeCollectionDescriptor] | None = None,
    *,
    tokens: SessionTokens,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        if ctx.principal is not None:
            return ctx
        ctx.principal = await _resolve_identity_principal(
            identity_collections=identity_collections,
            identity_id_fields=identity_id_fields,
            registry=registry,
            providers=providers or {},
            collections=collections or {},
            headers=ctx.headers,
            tokens=tokens,
        )
        return ctx

    return step


def _has_idp_provider(providers: dict[str, Any]) -> bool:
    return any(
        isinstance(provider, IROIDCProvider) and provider.is_idp
        for provider in providers.values()
    )


async def _resolve_idp_principal(
    bearer_token: str,
    identity_collections: dict[str, RuntimeIdentityDescriptor],
    collections: dict[str, RuntimeCollectionDescriptor],
    providers: dict[str, Any],
    registry: RepositoryRegistry,
) -> dict[str, Any] | None:
    issuer = idp.unverified_issuer(bearer_token)
    if not issuer:
        return None

    for collection_name, identity in identity_collections.items():
        for binding in identity.bindings:
            provider = providers.get(binding.provider)
            if not (isinstance(provider, IROIDCProvider) and provider.is_idp):
                continue
            if await idp.issuer_of(provider) != issuer:
                continue
            claims = await idp.verify_idp_token(bearer_token, provider)
            if claims is None:
                raise UnauthorizedError("Invalid IdP token")

            identifier_claim_path = binding.claim_mapping.get(binding.identifier, binding.identifier)
            if resolve_claim_path(claims, identifier_claim_path) is None:
                return _build_service_principal(claims, identity, binding)

            collection = collections[collection_name]
            try:
                record = await provisioning.provider_binding(binding).sign_in(
                    claims,
                    provisioning.records_of(registry, collections),
                    collection_name,
                    collection.id_field,
                )
            except provisioning.REFUSALS as error:
                raise UnauthorizedError(str(error)) from error
            if record is None:
                raise UnauthorizedError("User not found and auto-provisioning is disabled")
            return _build_principal(
                record,
                id_field=collection.id_field,
                identity_collection=collection_name,
                identity=identity,
                roles=_roles_from_claims(claims, identity, binding),
            )
    return None


def _roles_from_claims(
    claims: dict[str, Any],
    identity: RuntimeIdentityDescriptor | None,
    binding: IRProviderBinding | None,
) -> Any:
    roles_field = identity.roles_field if identity is not None else None
    if roles_field is None:
        return claims.get("roles") or claims.get("role")
    claim_path = (
        binding.claim_mapping.get(roles_field, roles_field)
        if binding is not None
        else roles_field
    )
    return resolve_claim_path(claims, claim_path)


def _build_service_principal(
    claims: dict[str, Any],
    identity: RuntimeIdentityDescriptor,
    binding: IRProviderBinding | None = None,
) -> dict[str, Any]:
    sub = str(claims["sub"])
    roles = _roles_from_claims(claims, identity, binding)
    roles_list: list[str] = []
    if isinstance(roles, list):
        roles_list = [str(r) for r in roles]
    elif isinstance(roles, str):
        roles_list = [roles]
    return {
        "sub": sub,
        "client_id": claims.get("azp") or claims.get("client_id") or sub,
        "is_service": True,
        "roles": roles_list,
        "record": None,
        "identity_collection": None,
    }


async def _resolve_jwt_principal(
    token: str,
    identity_collections: dict[str, RuntimeIdentityDescriptor],
    identity_id_fields: dict[str, str],
    registry: RepositoryRegistry,
    tokens: SessionTokens,
) -> dict[str, Any] | None:
    claims = tokens.decode(token)
    if claims is None:
        return None

    sub = claims.get("sub")
    collection_name = claims.get("identity_collection")
    if not sub or not collection_name:
        return None

    identity = identity_collections.get(collection_name)
    if identity is None:
        return None

    id_field = identity_id_fields.get(collection_name)
    if id_field is None:
        return None

    documents = await registry.for_collection(collection_name).list(collection_name)
    for doc in documents:
        if str(doc.get(id_field, "")) == sub:
            return _build_principal(
                doc,
                id_field=id_field,
                identity_collection=collection_name,
                identity=identity,
            )

    return None


async def _resolve_identity_principal(
    identity_collections: dict[str, RuntimeIdentityDescriptor],
    identity_id_fields: dict[str, str],
    registry: RepositoryRegistry,
    providers: dict[str, Any],
    collections: dict[str, RuntimeCollectionDescriptor],
    headers: dict[str, str],
    tokens: SessionTokens,
) -> dict[str, Any] | None:
    bearer_token = extract_bearer_token(headers)
    if bearer_token is not None:
        if _has_idp_provider(providers) and idp.unverified_issuer(bearer_token) is not None:
            idp_principal = await _resolve_idp_principal(
                bearer_token,
                identity_collections,
                collections,
                providers,
                registry,
            )
            if idp_principal is not None:
                return idp_principal
            raise UnauthorizedError("Untrusted token issuer")

        jwt_principal = await _resolve_jwt_principal(
            bearer_token,
            identity_collections,
            identity_id_fields,
            registry,
            tokens,
        )
        if jwt_principal is not None:
            return jwt_principal

    for identity in identity_collections.values():
        id_field = identity_id_fields.get(identity.name)
        if id_field is None:
            continue
        principal = await _resolve_identity_for_collection(
            identity,
            id_field,
            registry.for_collection(identity.name),
            headers,
        )
        if principal is not None:
            return principal
    return None


async def _resolve_identity_for_collection(
    identity: RuntimeIdentityDescriptor,
    id_field: str,
    repository: BaseRepository,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    if identity.has_api_key:
        token = extract_api_key(headers)
        if token is not None:
            return await _find_principal(
                repository,
                collection_name=identity.name,
                field_name="_auth.apiKey",
                field_value=token,
                id_field=id_field,
                identity=identity,
            )

    pw_binding = identity.get_binding("password")
    if pw_binding is not None:
        credentials = _extract_basic_credentials(headers)
        if credentials is not None:
            identifier_value, password = credentials
            return await _find_principal_with_password(
                repository=repository,
                collection_name=identity.name,
                identifier_field=pw_binding.identifier,
                identifier_value=identifier_value,
                password=password,
                id_field=id_field,
                identity=identity,
            )

    return None


def _extract_basic_credentials(headers: dict[str, str]) -> tuple[str, str] | None:
    authorization = headers.get("Authorization") or headers.get("authorization")
    if authorization is None or not authorization.startswith("Basic "):
        return None

    encoded = authorization.removeprefix("Basic ").strip()
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise UnauthorizedError("Invalid basic authorization") from exc

    if ":" not in decoded:
        raise UnauthorizedError("Invalid basic authorization")

    username, password = decoded.split(":", 1)
    if not username or not password:
        raise UnauthorizedError("Invalid basic authorization")
    return username, password


async def _find_principal(
    repository: BaseRepository,
    collection_name: str,
    field_name: str,
    field_value: str,
    id_field: str,
    identity: RuntimeIdentityDescriptor,
) -> dict[str, Any] | None:
    documents = await repository.list(collection_name)
    for document in documents:
        actual_value = get_nested_field(document, field_name)
        if str(actual_value or "") != field_value:
            continue
        return _build_principal(
            document,
            id_field=id_field,
            identity_collection=collection_name,
            identity=identity,
        )
    return None


async def _find_principal_with_password(
    repository: BaseRepository,
    collection_name: str,
    identifier_field: str,
    identifier_value: str,
    password: str,
    id_field: str,
    identity: RuntimeIdentityDescriptor,
) -> dict[str, Any] | None:
    documents = await repository.list(collection_name)
    document = find_document_with_password(
        documents,
        identifier_field=identifier_field,
        identifier_value=identifier_value,
        password=password,
    )
    if document is None:
        return None

    return _build_principal(
        document,
        id_field=id_field,
        identity_collection=collection_name,
        identity=identity,
    )


def _build_principal(
    document: dict[str, Any],
    id_field: str,
    identity_collection: str,
    identity: RuntimeIdentityDescriptor | None = None,
    roles: Any = None,
) -> dict[str, Any]:
    subject = document.get(id_field)
    if subject is None:
        raise UnauthorizedError(
            f"Identity record missing canonical id field: {id_field}"
        )

    record = {k: v for k, v in document.items() if k != "_auth"}
    record.pop("password", None)

    principal: dict[str, Any] = {
        "sub": str(subject),
        "identity_collection": identity_collection,
        "record": record,
    }

    if roles is None:
        roles_config = identity.roles if identity is not None else None
        roles_field = identity.roles_field if identity is not None else None
        auth_data = document.get("_auth")
        if roles_config is not None and isinstance(auth_data, dict):
            roles = auth_data.get("roles")
        elif roles_field is not None:
            roles = document.get(roles_field)
        else:
            roles = document.get("roles") or document.get("role")

    if isinstance(roles, list):
        principal["roles"] = [str(role) for role in roles]
    elif isinstance(roles, str):
        principal["roles"] = [roles]
    return principal
