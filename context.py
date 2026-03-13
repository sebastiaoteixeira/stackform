from dataclasses import dataclass
from typing import Any


@dataclass
class RequestContext:
    method: str
    path: str
    api_version: str | None
    collection: str | None
    operation: str | None
    url_params: dict[str, str]
    body: dict[str, Any] | None
    response: dict[str, Any] | None
