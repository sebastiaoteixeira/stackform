"""Auth configuration building for backend code generation.

Converts IR identity collections and providers into auth configuration descriptors.
"""

from typing import Any

from yaml_api_generator.ir import (
    IRCollection,
    IRIdentityCollection,
    IROIDCProvider,
    IRSAMLProvider,
    flatten_role_hierarchy,
)
from ..compile_context import (
    AuthConfig,
    IdpProviderDescriptor,
    IdentityCollectionDescriptor,
)


class AuthBuilder:
    """Builds auth configuration from IR identity collections."""

    def build_auth_config(
        self,
        identity_map: dict[str, IRIdentityCollection],
        collections: dict[str, IRCollection],
        providers: dict[str, Any],
        datastore_types: dict[str, str],
        requires_principal: bool,
        login_paths: dict[str, str],
    ) -> AuthConfig:
        """Build auth configuration descriptor.

        Args:
            identity_map: Identity collection IR objects
            collections: Collection IR objects
            providers: Provider configurations
            datastore_types: Collection name -> resolved datastore type
            requires_principal: Whether any route is closed to anonymous callers
            login_paths: Identity collection name -> relative path of its declared login route

        Returns:
            Auth configuration descriptor
        """
        if not identity_map:
            return AuthConfig(
                enabled=requires_principal,
                identity_collections=[],
                has_password_auth=False,
                has_api_key_auth=False,
                providers=providers,
            )

        descriptors: list[IdentityCollectionDescriptor] = []
        has_password = False
        has_api_key = False
        has_oidc = any(isinstance(p, IROIDCProvider) for p in providers.values())
        has_saml = any(isinstance(p, IRSAMLProvider) for p in providers.values())
        has_idp = any(
            isinstance(p, IROIDCProvider) and p.is_idp for p in providers.values()
        )
        has_app_oidc = any(
            isinstance(p, IROIDCProvider) and not p.is_idp for p in providers.values()
        )
        role_hierarchies: dict[str, dict[str, set[str]]] = {}
        idp_providers = self._build_idp_providers(providers)

        for name, identity in identity_map.items():
            col = collections[name]
            descriptors.append(
                IdentityCollectionDescriptor(
                    name=name,
                    bindings=identity.bindings,
                    id_field=col.idField,
                    id_format=col.idFormat,
                    roles=identity.roles,
                    roles_field=identity.roles_field,
                    issues_jwt=identity.issues_sessions(providers),
                    datastore_type=datastore_types.get(name, "mongodb"),
                    login=identity.login,
                    default_role=identity.default_role(col),
                    declared_login_path=login_paths.get(name),
                )
            )
            if identity.has_password:
                has_password = True
            if identity.has_api_key:
                has_api_key = True
            if identity.roles is not None and identity.roles.hierarchy:
                role_hierarchies[name] = flatten_role_hierarchy(identity.roles.hierarchy)

        return AuthConfig(
            enabled=True,
            identity_collections=descriptors,
            has_password_auth=has_password,
            has_api_key_auth=has_api_key,
            has_oidc_auth=has_oidc,
            has_saml_auth=has_saml,
            has_idp_auth=has_idp,
            has_app_oidc_auth=has_app_oidc,
            idp_providers=idp_providers,
            providers=providers,
            role_hierarchies=role_hierarchies,
        )

    @staticmethod
    def _build_idp_providers(providers: dict[str, Any]) -> list[IdpProviderDescriptor]:
        result = []
        for p in providers.values():
            if not (isinstance(p, IROIDCProvider) and p.is_idp):
                continue
            if not p.discovery_url:
                continue
            result.append(IdpProviderDescriptor(
                name=p.name,
                discovery_url=p.discovery_url,
                client_id=p.client_id,
                issuer=p.issuer,
                audiences=p.audiences,
            ))
        return result
