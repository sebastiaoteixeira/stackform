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
from ..compile_context import AuthConfig, IdentityCollectionDescriptor


class AuthBuilder:
    """Builds auth configuration from IR identity collections."""

    def build_auth_config(
        self,
        identity_map: dict[str, IRIdentityCollection],
        collections: dict[str, IRCollection],
        providers: dict[str, Any],
        datastore_types: dict[str, str],
    ) -> AuthConfig:
        """Build auth configuration descriptor.

        Args:
            identity_map: Identity collection IR objects
            collections: Collection IR objects
            providers: Provider configurations
            datastore_types: Collection name -> resolved datastore type

        Returns:
            Auth configuration descriptor
        """
        if not identity_map:
            return AuthConfig(
                enabled=False,
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
        role_hierarchies: dict[str, dict[str, set[str]]] = {}

        external = {
            n for n, p in providers.items()
            if isinstance(p, (IROIDCProvider, IRSAMLProvider))
        }
        for name, identity in identity_map.items():
            col = collections[name]
            issues_jwt = identity.has_password or any(
                b.provider in external for b in identity.bindings
            )
            descriptors.append(
                IdentityCollectionDescriptor(
                    name=name,
                    bindings=list(identity.bindings),
                    id_field=col.idField,
                    roles=identity.roles,
                    roles_field=identity.roles_field,
                    issues_jwt=issues_jwt,
                    datastore_type=datastore_types.get(name, "mongodb"),
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
            providers=providers,
            role_hierarchies=role_hierarchies,
        )
