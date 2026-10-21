"""Identity and auth entity transformation to IR.

Validates auth entities, role hierarchies, and implicit auth fields.
"""

from typing import Any, cast

from yaml_api_generator.ir import (
    IRCollection,
    IRIdentityCollection,
    IRProviderBinding,
    IRProviderRelation,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors

from ..roles_config import parse_roles_config


class IdentityTransformer:
    """Transforms auth entities to identity collections and validates roles."""

    def transform(
        self,
        entities_data: dict[str, Any],
        collections: dict[str, IRCollection],
        repo_entity_map: dict[str, str],
    ) -> dict[str, IRIdentityCollection]:
        """Transform auth entities to identity collections.

        Args:
            entities_data: Raw entity configurations from YAML
            collections: Already-built collection IR objects
            repo_entity_map: Repository name to entity name mapping

        Returns:
            Dictionary of identity collections

        Raises:
            ConfigErrors: If role field validation fails
        """
        identity_collections: dict[str, IRIdentityCollection] = {}
        for repo_name, entity_name in repo_entity_map.items():
            entity_data = entities_data.get(entity_name)
            if not isinstance(entity_data, dict):
                continue
            if str(entity_data.get("type", "base")) != "auth":
                continue
            if repo_name not in collections:
                continue
            auth_data = entity_data.get("auth", {})
            identifier = auth_data.get("identifier") if isinstance(auth_data, dict) else None
            via = self._normalize_via(
                auth_data.get("via") if isinstance(auth_data, dict) else None
            )
            roles_field = auth_data.get("roles") if isinstance(auth_data, dict) else None

            if roles_field is not None:
                role_errors = self._validate_roles_field(
                    entity_name, roles_field, collections[repo_name].fields
                )
                if role_errors:
                    raise ConfigErrors(role_errors)

            roles_config, roles_errors = parse_roles_config(
                "entities", entity_name, entity_data.get("roles")
            )
            if roles_errors:
                raise ConfigErrors(roles_errors)

            via_bindings = [
                IRProviderBinding(provider=entry, identifier=identifier or "")
                if isinstance(entry, str)
                else IRProviderBinding(
                    provider=entry["provider"],
                    identifier=entry.get("identifier", identifier or ""),
                    claim_mapping=entry.get("claim_mapping", {}),
                    auto_provision=entry.get("auto_provision", True),
                    relations={
                        fk: IRProviderRelation(
                            collection=spec["collection"],
                            match=spec.get("match", {}),
                        )
                        for fk, spec in (entry.get("relations") or {}).items()
                    },
                )
                for entry in via
                if isinstance(entry, dict) or identifier
            ]
            bindings = tuple(via_bindings)
            identity_collections[repo_name] = IRIdentityCollection(
                name=repo_name,
                bindings=bindings,
                roles=roles_config,
                roles_field=roles_field,
            )
        return identity_collections

    def validate_auth_fields(
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
                        path=f"entities.{name}.fields.password",
                        hint="Remove the password field from YAML",
                    )
                )
            if "passwordHash" in fields:
                errors.append(
                    ConfigError(
                        code="AUTH_PASSWORD_HASH_FIELD_FORBIDDEN",
                        message="passwordHash is implicit storage when auth.via includes password",
                        path=f"entities.{name}.fields.passwordHash",
                        hint="Remove the passwordHash field from YAML",
                    )
                )
        return errors

    def _normalize_via(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return cast(list[str], list(value))
        return []

    def _validate_roles_field(
        self, entity_name: str, roles_field: str, fields: dict[str, Any]
    ) -> list[ConfigError]:
        if roles_field not in fields:
            return [
                ConfigError(
                    code="AUTH_ROLES_FIELD_NOT_FOUND",
                    message=f"Roles field '{roles_field}' not found in entity '{entity_name}'",
                    path=f"entities.{entity_name}.auth.roles",
                )
            ]
        field_cfg = fields[roles_field]
        if not isinstance(field_cfg, dict) or field_cfg.get("type") != "enum":
            return [
                ConfigError(
                    code="AUTH_ROLES_FIELD_NOT_ENUM",
                    message=f"Roles field '{roles_field}' must be of type 'enum'",
                    path=f"entities.{entity_name}.fields.{roles_field}",
                )
            ]
        return []
