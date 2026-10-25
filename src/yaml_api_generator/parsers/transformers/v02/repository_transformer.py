"""Repository configuration transformation to IR.

Validates CRUD operations, query commands, and operation definitions.
"""

from collections.abc import Callable, Collection
from typing import Any

from yaml_api_generator.ir import CRUD_OPERATIONS, IROperation, IRRepository
from yaml_api_generator.parsers.yaml_parser import ConfigError
from .datastore_transformer import resolve_binding


def _identity_handler(handler: str | None) -> str | None:
    return handler


class RepositoryTransformer:
    """Transforms repository configurations to IRRepository objects."""

    _QUERY_COMMANDS: frozenset[str] = frozenset({
        "find", "findOne", "aggregate", "countDocuments", "estimatedDocumentCount",
        "distinct", "insertOne", "insertMany", "updateOne", "updateMany",
        "replaceOne", "deleteOne", "deleteMany", "findOneAndUpdate",
        "findOneAndReplace", "findOneAndDelete", "bulkWrite",
    })

    _QUERY_REQUIRED_FIELDS: dict[str, str] = {
        "find": "filter",
        "findOne": "filter",
        "countDocuments": "filter",
        "deleteOne": "filter",
        "deleteMany": "filter",
        "updateOne": "filter",
        "updateMany": "filter",
        "replaceOne": "filter",
        "findOneAndUpdate": "filter",
        "findOneAndReplace": "filter",
        "findOneAndDelete": "filter",
        "distinct": "filter",
        "aggregate": "pipeline",
        "insertOne": "document",
        "insertMany": "documents",
        "bulkWrite": "requests",
    }

    def transform(
        self,
        repos_data: dict[str, Any],
        defaults: dict[str, Any],
        datastore_names: set[str] | None = None,
        default_datastore: str = "default",
        datastore_types: dict[str, str] | None = None,
        handler_resolver: Callable[[str | None], str | None] = _identity_handler,
        file_datastore_names: Collection[str] = frozenset(),
    ) -> tuple[dict[str, IRRepository], list[ConfigError]]:
        """Transform repository configurations to IR.

        Args:
            repos_data: Raw repository configurations from YAML
            defaults: Default operation configuration

        Returns:
            Tuple of (repositories dict, validation errors)
        """
        repositories: dict[str, IRRepository] = {}
        errors: list[ConfigError] = []

        for repo_name, repo_cfg in repos_data.items():
            if not isinstance(repo_cfg, dict):
                continue

            entity = repo_cfg.get("entity")
            abstract = bool(repo_cfg.get("abstract"))
            crud_raw: list[str] | None = repo_cfg.get("crud")
            operations_raw: dict[str, Any] = repo_cfg.get("operations", {})

            if datastore_names is None:
                datastore = repo_cfg.get("datastore") or default_datastore
            else:
                datastore, binding_error = resolve_binding(
                    repo_name, repo_cfg, datastore_names, default_datastore, file_datastore_names
                )
                if binding_error is not None:
                    errors.append(binding_error)

            if crud_raw is not None and entity is None:
                errors.append(ConfigError(
                    code="CRUD_WITHOUT_ENTITY",
                    message=f"Repository '{repo_name}' specifies 'crud' but has no 'entity'",
                    path=f"repositories.{repo_name}.crud",
                ))

            crud_ops: tuple[str, ...]
            if crud_raw is not None:
                invalid = [op for op in crud_raw if op not in CRUD_OPERATIONS]
                for op in invalid:
                    errors.append(ConfigError(
                        code="CRUD_OPERATION_INVALID",
                        message=f"Unknown CRUD operation '{op}' in repository '{repo_name}'",
                        path=f"repositories.{repo_name}.crud",
                    ))
                crud_ops = tuple(op for op in crud_raw if op in CRUD_OPERATIONS)
            else:
                crud_ops = CRUD_OPERATIONS

            ops_dict: dict[str, IROperation] = {}
            for op_name, op_cfg in operations_raw.items():
                if not isinstance(op_cfg, dict):
                    continue
                query = op_cfg.get("query")
                handler = op_cfg.get("handler")

                if query is None and handler is None:
                    errors.append(ConfigError(
                        code="OPERATION_MISSING_QUERY_OR_HANDLER",
                        message=f"Operation '{op_name}' in repository '{repo_name}' must have 'query' or 'handler'",
                        path=f"repositories.{repo_name}.operations.{op_name}",
                    ))
                    continue

                if query is not None:
                    ds_type = (datastore_types or {}).get(datastore)
                    op_path = f"repositories.{repo_name}.operations.{op_name}.query"
                    if "sql" in query:
                        if ds_type in ("mongodb", "mongo"):
                            errors.append(ConfigError(
                                code="QUERY_FORM_MISMATCH",
                                message=f"Operation '{op_name}' uses a SQL query but datastore '{datastore}' is MongoDB",
                                path=f"{op_path}.sql",
                            ))
                        elif not isinstance(query.get("sql"), str) or not query["sql"].strip():
                            errors.append(ConfigError(
                                code="QUERY_SQL_INVALID",
                                message=f"Operation '{op_name}' has an empty or non-string 'sql'",
                                path=f"{op_path}.sql",
                            ))
                    elif ds_type in ("postgres", "postgresql"):
                        errors.append(ConfigError(
                            code="QUERY_FORM_MISMATCH",
                            message=f"Operation '{op_name}' uses a MongoDB command but datastore '{datastore}' is relational; use 'sql'",
                            path=f"{op_path}.command",
                        ))
                    else:
                        command = query.get("command")
                        if command not in self._QUERY_COMMANDS:
                            errors.append(ConfigError(
                                code="QUERY_COMMAND_UNKNOWN",
                                message=f"Unknown query command '{command}' in operation '{op_name}'",
                                path=f"{op_path}.command",
                            ))
                        else:
                            required_field = self._QUERY_REQUIRED_FIELDS.get(command)
                            if required_field and required_field not in query:
                                errors.append(ConfigError(
                                    code="QUERY_MISSING_FIELD",
                                    message=f"Query command '{command}' requires field '{required_field}'",
                                    path=op_path,
                                ))
                            if entity is None and query.get("collection") is None and not abstract:
                                errors.append(ConfigError(
                                    code="QUERY_MISSING_COLLECTION",
                                    message=f"Operation '{op_name}' has no entity on repository and no 'collection' in query",
                                    path=op_path,
                                ))

                ops_dict[op_name] = IROperation(
                    name=op_name,
                    query=query,
                    handler=handler_resolver(handler),
                    include_deleted=op_cfg.get("includeDeleted", False),
                )

            if entity is None and not ops_dict and not abstract:
                errors.append(ConfigError(
                    code="REPOSITORY_EMPTY",
                    message=f"Repository '{repo_name}' must have at least 'entity' or 'operations'",
                    path=f"repositories.{repo_name}",
                ))
                continue

            repositories[repo_name] = IRRepository(
                name=repo_name,
                entity=entity,
                crud=crud_ops,
                operations=ops_dict,
                datastore=datastore,
                abstract=abstract,
                inherits=repo_cfg.get("_inherits"),
            )

        return repositories, errors
