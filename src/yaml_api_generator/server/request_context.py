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
