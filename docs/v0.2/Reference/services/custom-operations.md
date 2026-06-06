---
title: "Custom Service Operations"
description: Custom operations attach your own Python handler functions to a service and expose them as HTTP routes, alongside the generated CRUD operations.
---

Custom operations attach your own Python handler functions to a service and expose them as HTTP routes, alongside the generated CRUD operations. Use them when a route needs behavior that the built-in CRUD operations do not provide (for example, "publish a record" or "archive a record").

## Declaration

A custom operation is a named entry under a service's `operations:` whose value carries a `handler:`:

```yaml
imports:
  ops: myapp.handlers.ops

services:
  myCollection:
    repository: myCollection
    operations:
      publish: { handler: ops.publish_record }
      archive: { handler: ops.archive_record }
```

`handler:` is `<importAlias>.<functionName>`. The alias is resolved against the
`imports:` map by splitting on the first dot only: `ops` maps to
`myapp.handlers.ops`, so `ops.publish_record` resolves to the dotted path
`myapp.handlers.ops.publish_record`. If the alias before the first dot is not
present in `imports:`, the handler string is used verbatim as a fully qualified
dotted path, so you can also write `handler: myapp.handlers.ops.publish_record`
directly.

## Exposing via a controller

A custom operation has no naming convention, so the controller operation that
exposes it MUST set both `method:` and `path:`. Omitting either is a generate-time
error (`DESUGAR_CUSTOM_OP_MISSING_ROUTE`). There is no method/path inference for
custom operations (only the built-in CRUD and auth operations have conventional
routes).

```yaml
api:
  basePath: /api
  version: v1

controllers:
  myCollection:
    service: myCollection
    base_path: /my-collection
    operations:
      publish:
        method: POST
        path: "/{id}/publish"
        access: "*"
      archive:
        method: POST
        path: "/{id}/archive"
        access: moderator
```

The full route path is `basePath` + version segment + `base_path` + the
operation `path:`. With the `api:` block above, `publish` is served at
`POST /api/v1/my-collection/{id}/publish`.

A custom controller operation only produces a route when the referenced service
defines a matching custom operation; the controller operation name must match the
service operation name.

## Handler signature (generated FastAPI / raw backend)

In the generated backend the handler receives the FastAPI `Request` and returns a
value that becomes the JSON response body:

```python
# myapp/handlers/ops.py
from datetime import datetime, timezone

from fastapi import Request, HTTPException


async def publish_record(request: Request):
    record_id = request.path_params["id"]
    body = await request.json()

    # Do your own data access here. Import the generated repository/service,
    # or talk to the database directly -- the handler is plain application code.
    if body.get("draft"):
        raise HTTPException(status_code=400, detail="Cannot publish a draft")

    return {
        "id": record_id,
        "published": True,
        "publishedAt": datetime.now(timezone.utc).isoformat(),
    }
```

Notes:

- The handler is invoked as `await handler(request)`. Read path and query
  parameters from `request.path_params` / `request.query_params`, and the parsed
  body with `await request.json()`.
- The handler owns its own data access and response shaping. There is no injected
  repository, principal, or request context for this handler kind.
- Raise `fastapi.HTTPException` to return a controlled status. An uncaught
  exception surfaces as a 500.
- Returning a dict or list serializes to JSON. You may also return a FastAPI
  `Response` directly.

> **Support note**
>
> Custom service-operation routes are generated only by the `fastapi` target.
> The `raw` and `drf` targets do not emit a route for a service-level custom
> handler. If you target `raw` or `drf` and need custom data access, use a
> repository-level operation (see below).

## Handler signature (`yaml-api run` dev server)

The in-process dev server runs the same `handler:` declaration as a pipeline step.
The contract is different: the handler receives a `RequestContext`, sets
`context.response`, and returns the context.

```python
# myapp/handlers/ops.py
from datetime import datetime, timezone


async def publish_record(context):
    record_id = context.url_params["id"]
    doc = await context.repository.get(record_id)
    if doc.get("published"):
        context.response = {"detail": "Already published"}
        return context

    context.response = await context.repository.update(
        record_id,
        {"published": True, "publishedAt": datetime.now(timezone.utc).isoformat()},
    )
    return context
```

The `RequestContext` exposes:

| Attribute | Description |
|-----------|-------------|
| `context.repository` | Repository instance bound to the service's repository |
| `context.url_params` | Path and query parameters |
| `context.body` | Parsed request body (or `None`) |
| `context.principal` | Authenticated principal as a dict (`principal["sub"]`, `principal["identity_collection"]`, `principal["record"]`) or `None` |
| `context.headers` | Request headers |
| `context.response` | Set this to the value you want serialized as the response |

For controlled "not found" handling under the dev server, raise the shared error:

```python
from yaml_api_generator.server.common.steps import NotFoundError
```

If you want one handler module to run under both modes, branch on what it
receives, or keep separate handlers and point each spec at the right one.

## Access control

Custom operations participate in the same access control as built-in operations.
Set `access:` on the controller operation exactly as you would for `create`,
`update`, etc. The example above gates `publish` with `"*"` (any authenticated
principal) and `archive` with the `moderator` role.

> **Enforcement status**
>
> Roles (exact match), `identity:<entity>` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `yaml-api run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## Repository-level operations (declarative alternative)

If you only need a database query and not arbitrary Python, declare the operation
on the repository instead of writing a handler. A repository operation is either a
`query:` (a named MongoDB command) or a `handler:` invoked as
`await handler(**kwargs)`:

```yaml
repositories:
  myCollection:
    entity: myEntity
    operations:
      recent:
        query:
          command: find
          filter: { published: true }
      featured:
        handler: ops.featured_records
```

`query.command` must be one of the allowed MongoDB commands (for example `find`,
`findOne`, `aggregate`, `countDocuments`, `distinct`, `updateMany`,
`deleteMany`). Some commands require a field (`find`/`findOne` require `filter`).
A repository without an `entity:` must set `query.collection`
(`QUERY_MISSING_COLLECTION`). An operation that has neither `query:` nor `handler:`
is rejected (`OPERATION_MISSING_QUERY_OR_HANDLER`); an unknown command is
`QUERY_COMMAND_UNKNOWN`.

The two handler kinds differ in their arguments: a service custom-operation handler
receives the raw request (FastAPI) or a `RequestContext` (run), while a repository
`operations.<op>.handler` is called with keyword arguments. See
[Repository operations](../repositories/operations.md) for the full repository
operation model.
