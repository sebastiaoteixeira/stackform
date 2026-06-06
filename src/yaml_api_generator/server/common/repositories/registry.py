"""Registry of repositories keyed by datastore.

Resolves the repository backing a given collection through the
collection-to-datastore binding. A single-datastore spec yields a registry with
one repository, so the common case is unchanged.
"""

from collections.abc import Iterable

from .base import BaseRepository


class RepositoryRegistry:
    def __init__(
        self,
        repositories: dict[str, BaseRepository],
        bindings: dict[str, str],
        default: str,
    ) -> None:
        self._repositories = repositories
        self._bindings = bindings
        self._default = default

    @classmethod
    def single(
        cls, repository: BaseRepository, default: str = "default"
    ) -> "RepositoryRegistry":
        """Wrap a single repository as the default for every collection."""
        return cls({default: repository}, {}, default)

    def for_collection(self, collection: str | None) -> BaseRepository:
        datastore = self._bindings.get(collection, self._default)
        return self._repositories[datastore]

    def get(self, datastore: str) -> BaseRepository:
        return self._repositories[datastore]

    def all(self) -> Iterable[BaseRepository]:
        return self._repositories.values()
