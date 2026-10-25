"""Repository operations building for backend code generation.

Converts IR repository operations into serialized operation descriptors.
"""

from collections.abc import Mapping

from yaml_api_generator.ir import IRRepository
from yaml_api_generator.runtime.lifecycle import Lifecycle


class RepositoryBuilder:
    """Builds repository operation descriptors from IR."""

    def build_repository_operations(
        self,
        repositories: dict[str, IRRepository],
        lifecycles: Mapping[str, Lifecycle],
    ) -> dict[str, list[dict]]:
        """Map each repository name to the descriptors of its operations.

        `target_lifecycle` is the lifecycle of the collection an operation names in
        `query.collection`; an operation on its own collection carries None.
        """
        return {
            repo_name: [
                {
                    "name": op.name,
                    "query": op.query,
                    "handler": op.handler,
                    "include_deleted": op.include_deleted,
                    "target_lifecycle": _target_lifecycle(op.query, lifecycles),
                }
                for op in repo.operations.values()
            ]
            for repo_name, repo in repositories.items()
            if repo.operations
        }


def _target_lifecycle(query: Mapping | None, lifecycles: Mapping[str, Lifecycle]) -> Lifecycle | None:
    target = (query or {}).get("collection")
    return lifecycles.get(target, Lifecycle()) if target else None
