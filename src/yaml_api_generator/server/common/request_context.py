"""Request context data structure for pipeline processing.

RequestContext carries all request state through the pipeline:
- HTTP metadata (method, path, headers)
- Routing info (collection, operation, API version)
- Authentication state (principal)
- Repository instance
- Request body and response data

Each pipeline step receives and returns an updated RequestContext.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class RequestContext:
    method: str
    path: str
    api_version: str | None
    collection: str | None
    operation: str | None
    headers: dict[str, str]
    url_params: dict[str, str]
    repository: Any | None
    principal: dict[str, Any] | None
    body: dict[str, Any] | None
    response: Any | None
    repositories: Any | None = None
    query: dict[str, str | list[str]] | None = None
    cookies: dict[str, str] | None = None
    where_documents: list[dict[str, Any]] | None = None
    service_inputs: dict[str, Any] | None = None

    def repository_for(self, collection: str | None) -> Any:
        """Resolve the repository backing a collection (cross-store access)."""
        if self.repositories is None:
            return self.repository
        return self.repositories.for_collection(collection)
