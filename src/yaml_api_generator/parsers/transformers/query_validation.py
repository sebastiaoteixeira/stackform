"""Collection references inside repository operation queries.

A query may target another collection through ``query.collection``. That name
must be a concrete repository of the desugared spec, so a typo fails generation
instead of every target querying an empty, implicitly created collection.
"""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError


def validate_spec_queries(spec: dict[str, Any]) -> list[ConfigError]:
    repositories = {
        name: repository for name, repository in (spec.get("repositories") or {}).items()
        if isinstance(repository, dict)
    }
    collections = {name for name, repository in repositories.items() if not repository.get("abstract")}
    return [
        ConfigError(
            code="QUERY_COLLECTION_NOT_FOUND",
            message=f"Operation '{op_name}' queries unknown collection '{operation['query']['collection']}'",
            path=f"repositories.{repo_name}.operations.{op_name}.query.collection",
            hint=f"Use one of: {', '.join(sorted(collections))}",
        )
        for repo_name, repository in repositories.items()
        for op_name, operation in (repository.get("operations") or {}).items()
        if isinstance(operation, dict)
        and isinstance(operation.get("query"), dict)
        and "collection" in operation["query"]
        and operation["query"]["collection"] not in collections
    ]
