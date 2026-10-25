"""Repository operations building for backend code generation.

Converts IR repository operations into serialized operation descriptors.
"""

from yaml_api_generator.ir import IRRepository


class RepositoryBuilder:
    """Builds repository operation descriptors from IR."""

    def build_repository_operations(
        self,
        repositories: dict[str, IRRepository],
    ) -> dict[str, list[dict]]:
        """Build repository operations index.

        Args:
            repositories: Repository IR objects

        Returns:
            Dictionary mapping repository names to operation descriptors
        """
        result: dict[str, list[dict]] = {}
        for repo_name, repo in repositories.items():
            if repo.operations:
                result[repo_name] = [
                    {"name": op.name, "query": op.query, "handler": op.handler}
                    for op in repo.operations.values()
                ]
        return result
