"""Identity and auth transformation for v0.1 specifications.

Validates auth collections, their roles and implicit auth fields.
"""

from typing import Any, cast

from yaml_api_generator.ir import IRCollection, IRIdentityCollection, IRProviderBinding
from yaml_api_generator.parsers.yaml_parser import ConfigError

from ..roles import roles_config


class IdentityTransformer:
    """Transforms v0.1 auth collections to identity IR."""

    def transform(
        self,
        collections_data: dict[str, Any],
        collections: dict[str, IRCollection],
    ) -> dict[str, IRIdentityCollection]:
        """Transform auth collections to identity collections.

        Args:
            collections_data: Raw collection configurations from YAML
            collections: Already-built collection IR objects

        Returns:
            Dictionary of identity collections

        Raises:
            ConfigErrors: If a role hierarchy names an undeclared role or is cyclic
        """
        identity_collections: dict[str, IRIdentityCollection] = {}
        for name, collection in collections.items():
            if collection.type != "auth":
                continue
            collection_data = collections_data.get(name, {})
            identifier, via = self._extract_identity_auth(collection_data)
            bindings = tuple(
                IRProviderBinding(provider=p, identifier=identifier or "")
                for p in via
                if identifier
            )
            identity_collections[name] = IRIdentityCollection(
                name=name,
                bindings=bindings,
                roles=roles_config(f"collections.{name}.roles", collection_data.get("roles")),
            )
        return identity_collections

    def validate_implicit_auth_fields(
        self,
        collections: dict[str, IRCollection],
        identity_collections: dict[str, IRIdentityCollection],
    ) -> list[ConfigError]:
        """Validate implicit auth fields for password-based providers.

        Args:
            collections: Collection IR objects
            identity_collections: Identity collection IR objects

        Returns:
            List of validation errors
        """
        errors: list[ConfigError] = []
        for name, identity in identity_collections.items():
            if not identity.has_password:
                continue
            fields = collections[name].fields
            if "password" in fields:
                errors.append(
                    ConfigError(
                        code="AUTH_PASSWORD_FIELD_FORBIDDEN",
                        message="Password input is implicit when auth.via includes password",
                        path=f"collections.{name}.fields.password",
                        hint="Remove the password field from YAML",
                    )
                )
            if "passwordHash" in fields:
                errors.append(
                    ConfigError(
                        code="AUTH_PASSWORD_HASH_FIELD_FORBIDDEN",
                        message="passwordHash is implicit storage when auth.via includes password",
                        path=f"collections.{name}.fields.passwordHash",
                        hint="Remove the passwordHash field from YAML",
                    )
                )
        return errors

    def _extract_identity_auth(
        self, collection_data: dict[str, Any]
    ) -> tuple[str | None, list[str]]:
        auth_data = collection_data.get("auth")
        if isinstance(auth_data, dict):
            via = auth_data.get("via")
            normalized: list[str] = (
                [via] if isinstance(via, str)
                else cast(list[str], list(via)) if isinstance(via, list)
                else []
            )
            return auth_data.get("identifier"), normalized
        return None, []
