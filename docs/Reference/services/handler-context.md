# Reference: Handler Context

The `context` object is passed to every custom handler function. It provides access to the repository, request data, and the authenticated principal.

## `context` attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `context.repository` | `MongoRepository` | The MongoDB repository bound to this service's entity. Provides `list()`, `get(id)`, `create(data)`, `update(id, data)`, `replace(id, data)`, `delete(id)`. |
| `context.params` | `dict` | URL path parameters. For example, `context.params["id"]` on a route with `/{id}` in the path. |
| `context.body` | `dict` or `None` | The parsed JSON request body. `None` if the request has no body. |
| `context.principal` | `Principal` or `None` | The authenticated user, or `None` if the route is public / unauthenticated. |
| `context.now()` | `datetime` | Returns the current UTC datetime. |

## `principal` attributes

When `context.principal` is not `None`, it has the following attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `principal.sub` | `str` | The authenticated user's primary key value (their `id`). |
| `principal.record` | `dict` | The user's document from MongoDB, without the `_auth` namespace. Contains only the entity's declared fields. |
| `principal.roles` | `list[str]` | The user's roles as a list of strings (e.g., `["admin"]`). |

## Error handling

Raise exceptions from your handler to return HTTP error responses:

| Exception | HTTP Status | Use case |
|-----------|-------------|----------|
| `ValueError` | 400 Bad Request | Invalid input or business rule violation. |
| `NotFoundError` | 404 Not Found | Document does not exist. Import from `yaml_api_generator.runtime.steps.repositories`. |
| Any unhandled exception | 500 Internal Server Error | Unexpected errors. |

## Example

```python
from yaml_api_generator.runtime.steps.repositories import NotFoundError

async def publish(context):
    doc = await context.repository.get(context.params["id"])
    if doc is None:
        raise NotFoundError("Note not found")
    if doc["published"]:
        raise ValueError("Already published")
    return await context.repository.update(
        context.params["id"],
        {"published": True, "publishedAt": context.now()}
    )
```

## See Also

- [Custom operations](./custom-operations.md)
- [Services overview](./overview.md)
- [Tutorial 09: Custom Operations](../../Tutorial/09-custom-operations.md)
