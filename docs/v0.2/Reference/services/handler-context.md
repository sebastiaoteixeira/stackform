---
title: "Handler Context"
description: Custom operation handlers run under two contracts. Generated backends pass a target request object; the yaml-api run dev server passes a RequestContext pipeline object. This page documents both.
---

A custom operation runs different code depending on how you execute your spec. The
generated backends invoke your handler with their target request object. The
raw-ASGI target supplies a compatible request facade.
The `yaml-api run` dev server invokes your handler as a pipeline step that receives a
`RequestContext` and returns it. Write your handler for the target you intend to run;
the two contracts are not interchangeable.

Both kinds are wired through `services.<name>.operations.<op>.handler` plus an
`imports:` mapping, and both are exposed as routes through a controller operation that
sets `method:` and `path:` (see [Custom operations](./custom-operations.md)).

## Generated backend handler (`build`)

The generated route calls your function with the target request object:

```python
from fastapi import Request
from services.exceptions import NotFoundError

async def publish(request: Request):
    entity_id = request.path_params["id"]
    body = await request.json()
    ...
    return {"id": entity_id, "status": "published"}
```

| Source | How to read it |
|--------|----------------|
| Path parameters | `request.path_params["id"]` |
| Query parameters | `request.query_params.get("draft")` |
| Request body | `await request.json()` |
| Headers | `request.headers.get("authorization")` |

The principal is NOT injected, and custom FastAPI routes are NOT run through the
authentication or authorization pipeline: the generated route invokes your handler
directly, with no `require_principal` and no access-rule check, even when neighboring
CRUD routes on the same controller are protected. If the action must be restricted,
read the `Authorization` / `X-API-Key` header and verify the caller inside your
handler. (The `yaml-api run` dev server differs: there a custom handler runs after the
route's authenticate and authorize steps, and the resolved caller is available as
`context.principal` -- see below.)

Your handler owns its database access (import the service or repository it needs) and
owns its response: return a JSON-serializable value (dict or list) and it is sent as
the body. An uncaught exception becomes a 500. The CRUD-route mapping of
`NotFoundError` to 404 and `ValidationError` to 422 does NOT apply to custom handlers;
raise `fastapi.HTTPException` to return a controlled status code.

```python
from fastapi import HTTPException

async def publish(request: Request):
    entity_id = request.path_params["id"]
    if not entity_id:
        raise HTTPException(status_code=400, detail="Missing entity id")
    ...
```

## `run` dev server handler (`yaml-api run`)

Under `yaml-api run`, a handler is a pipeline step. It receives the request
`RequestContext`, mutates it, and returns it:

```python
from yaml_api_generator.server.common.steps import NotFoundError

async def publish(context):
    entity_id = context.url_params["id"]
    doc = await context.repository.get(entity_id)
    if doc is None:
        raise NotFoundError("Entity not found")
    if doc["status"] == "published":
        raise ValueError("Already published")
    context.response = await context.repository.update(
        entity_id,
        {"status": "published"},
    )
    return context
```

### `context` attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `context.repository` | repository | The repository bound to this service's entity. Provides `list()`, `get(id)`, `create(data)`, `update(id, data)`, `replace(id, data)`, `delete(id)`. |
| `context.url_params` | `dict` | Path parameters. For a route with `/{id}`, use `context.url_params["id"]`. |
| `context.body` | `dict` or `None` | The parsed JSON request body. `None` if the request had no body. |
| `context.headers` | `dict` | Request headers (lowercased keys). |
| `context.principal` | `dict` or `None` | The authenticated caller, or `None` on a public/unauthenticated route. |
| `context.method` / `context.path` | `str` | The HTTP method and matched path. |
| `context.response` | `Any` | What you set here is JSON-encoded and returned. A handler MUST assign this and `return context`. |

There is no `context.now()`; use `datetime.now(timezone.utc)` from the standard
library if you need a timestamp.

### `principal` keys

When `context.principal` is not `None` it is a plain dict, not an object. Index it:

| Key | Type | Description |
|-----|------|-------------|
| `principal["sub"]` | `str` | The caller's primary-key value (their id). |
| `principal["identity_collection"]` | `str` | The auth entity the caller belongs to. |
| `principal["record"]` | `dict` | The caller's stored document, with `_auth` and `password` removed. Read other identity fields via `principal["record"]["<field>"]`. |
| `principal["roles"]` | `list[str]` | The caller's roles, present only when the identity declares a roles field. |

### Error handling

Raise exceptions to map onto HTTP status codes:

| Exception | HTTP status | Use case |
|-----------|-------------|----------|
| `NotFoundError` | 404 Not Found | Record does not exist. Import from `yaml_api_generator.server.common.steps`. |
| `ValueError` | 422 Unprocessable Entity | Invalid input or a business-rule violation. |
| `UnauthorizedError` | 401 Unauthorized | Missing or invalid credentials. |
| `ForbiddenError` | 403 Forbidden | Authenticated but not allowed. |
| Any other exception | 500 Internal Server Error | Unexpected errors. |

## Repository-level handlers

A repository operation can also point at a handler:

```yaml
repositories:
  myCollection:
    operations:
      recent: { handler: my_collection.recent }
```

This handler is called differently from the two request-handler contracts above: the
generated repository invokes it as `await <handler>(**kwargs)`, passing the operation's
arguments as keyword arguments. There is no `Request` and no `RequestContext`. Use this
form for data-access logic that the service layer drives; see
[Repository operations](../repositories/operations.md).

## See Also

- [Custom operations](./custom-operations.md)
- [Services overview](./overview.md)
- [Repository operations](../repositories/operations.md)
- [Tutorial 09: Custom Operations](../../Tutorial/09-custom-operations.md)
