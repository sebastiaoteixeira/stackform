"""Auth configuration building for backend code generation.

Converts IR identity collections and providers into auth configuration descriptors.
"""

from typing import Any

from yaml_api_generator.ir import IRCollection, IRIdentityCollection, IROIDCProvider, IRSAMLProvider
from ..compile_context import AuthConfig, IdentityCollectionDescriptor


class AuthBuilder:
    """Builds auth configuration from IR identity collections."""

    def build_auth_config(
        self,
        identity_map: dict[str, IRIdentityCollection],
        collections: dict[str, IRCollection],
        providers: dict[str, Any],
    ) -> AuthConfig:
        """Build auth configuration descriptor.

        Args:
            identity_map: Identity collection IR objects
            collections: Collection IR objects
            providers: Provider configurations

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

        for name, identity in identity_map.items():
            col = collections[name]
            descriptors.append(
                IdentityCollectionDescriptor(
                    name=name,
                    bindings=list(identity.bindings),
                    id_field=col.idField,
                    roles=identity.roles,
                    roles_field=identity.roles_field,
                )
            )
            if identity.has_password:
                has_password = True
            if identity.has_api_key:
                has_api_key = True

        return AuthConfig(
            enabled=True,
            identity_collections=descriptors,
            has_password_auth=has_password,
            has_api_key_auth=has_api_key,
            has_oidc_auth=has_oidc,
            has_saml_auth=has_saml,
            providers=providers,
        )
