---
title: "Tutorial 09: Custom Operations"
description: Custom operations with handler functions (e.g. publishing a note), wiring imports, and the two handler contracts.
---

**Concept introduced:** Custom operations backed by handler functions (for example, publishing a note) that do not map to plain create/update/delete.

## When you need a custom operation

Standard CRUD (`list`, `get`, `create`, `update`, `replace`, `delete`) covers most cases. A custom operation handles a domain action that is not a plain write, such as `POST /notes/{id}/publish`. You attach a handler in three places:

- `imports:` maps a short alias to a Python module path.
- `services.<name>.operations.<op>: { handler: <alias>.<function> }` binds the handler to the service.
- `controllers.<name>.operations.<op>: { method, path }` exposes it as a route. Custom operations have no default verb or path, so both `method` and `path` are required (omitting them fails generation with `DESUGAR_CUSTOM_OP_MISSING_ROUTE`).

## The imports block

`imports:` maps aliases to dotted Python module paths. It lives at the top level of the spec:

```yaml
imports:
  notes: myapp.handlers.notes
```

Resolution splits a handler reference on the first dot: `notes.publish` becomes the alias `notes` plus the rest, `publish`. The alias is looked up in `imports`, so `notes.publish` resolves to `myapp.handlers.notes.publish`. If the first segment is not a declared alias, the whole reference is used verbatim as a dotted path. The module must be importable on `PYTHONPATH` when the app runs; place your package next to the generated backend or install it.

## Full spec

This spec sets `api: { basePath: /api, version: v1 }`, so every route below is prefixed with `/api/v1` (for example `POST /api/v1/notes/{id}/publish`).

```yaml
version: "0.2"

imports:
  notes: myapp.handlers.notes

api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  user:
    extends: base
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  note:
    extends: base
    fields:
      title: { type: string, required: true }
      body: { type: string }
      authorId: { type: ref, ref: user }
      published: { type: boolean, default: false }
      publishedAt: { type: datetime }

repositories:
  users:
    entity: user
  notes:
    entity: note

services:
  users:
    repository: users
  notes:
    repository: notes
    operations:
      publish: { handler: notes.publish }

controllers:
  users:
    service: users
    base_path: /users
    operations:
      register: { access: public }
      login: { access: public }

  notes:
    service: notes
    base_path: /notes
    access: public
    operations:
      create: { access: "*" }
      update:
        access:
          - moderator
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
      delete:
        access:
          - moderator
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
      publish:
        method: POST
        path: "/{id}/publish"
        access:
          - moderator
          - given:
              principal: identity:user
              document: notes
            when: principal.sub equals document.authorId
```

Notes on this spec:

- Roles come from an enum field plus `auth.roles: role`. The standalone entity-level `roles: { values, default, hierarchy }` block is parsed but not wired in v0.2, so do not rely on it. A new user's role is set only by the enum field's `default:`; clients cannot set `role`/`roles` on write (those keys are stripped).
- `register`/`login` routes are not generated unless you enable them with `api.operations.auth`, as shown above.
- `access: "*"` means any logged-in user; `public` means no auth; `moderator` is an exact role match; the `given`/`when` rule is an ownership check.

## Two handler contracts

The handler signature depends on the target you generate or run. Write the version that matches how you ship the app.

### Generated FastAPI (and raw) backend: `request: Request`

`yaml-api build myapp.yaml backend` (default target `fastapi`) emits a route that calls your handler with the FastAPI `Request` and awaits its return value. Read inputs off the request, do your own database access through the generated repository, and return a JSON-serializable value.

```python
# myapp/handlers/notes.py
from datetime import datetime, timezone

from fastapi import HTTPException, Request

from repositories.notes import NotesRepository
from dependencies.mongodb import get_database


async def publish(request: Request):
    note_id = request.path_params["id"]
    repo = NotesRepository(get_database())
    doc = await repo.get(note_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Note not found")
    if doc["published"]:
        raise HTTPException(status_code=409, detail="Already published")
    return await repo.update(
        note_id,
        {"published": True, "publishedAt": datetime.now(timezone.utc).isoformat()},
    )
```

Raise `HTTPException` for controlled error responses. Any other uncaught exception becomes a 500. The custom-op route on the FastAPI backend does not run the CRUD access pipeline, so if the action must be restricted, enforce it inside the handler (resolve the principal and check it yourself).

### `yaml-api run` dev server: `context: RequestContext`

The in-process dev server invokes the handler as a pipeline step. It receives and returns a `RequestContext`: read inputs from the context, set `context.response`, and return the context.

```python
# myapp/handlers/notes.py (dev-server variant)
from datetime import datetime, timezone

from yaml_api_generator.server.common.steps import NotFoundError


async def publish(context):
    note_id = context.url_params["id"]
    doc = await context.repository.get(note_id)
    if doc is None:
        raise NotFoundError("Note not found")
    if doc["published"]:
        raise ValueError("Already published")
    context.response = await context.repository.update(
        note_id,
        {"published": True, "publishedAt": datetime.now(timezone.utc).isoformat()},
    )
    return context
```

`RequestContext` fields available to a handler:

- `context.repository` -- the repository bound to this service's collection.
- `context.url_params` -- path parameters, for example `context.url_params["id"]`.
- `context.body` -- the parsed JSON body, or `None`.
- `context.headers` -- the request headers.
- `context.principal` -- a dict for the authenticated user (or `None` on public routes): `principal["sub"]`, `principal["identity_collection"]`, `principal["record"]` (the user document with `_auth` and `password` stripped), and `principal["roles"]` when a roles field is configured. It is a plain dict, not an object with attributes.

There is no `context.now()`; build timestamps yourself. Raise `NotFoundError` (imported from `yaml_api_generator.server.common.steps`) for a 404, or a plain `ValueError` for a 422. Under `run`, a non-public custom route resolves the principal and applies its access rules before your handler runs.

> **Enforcement status**
>
> Roles (exact match), `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `yaml-api run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## Declarative alternative: repository query operations

If your custom action is just a parameterized read, you can avoid a handler entirely with a repository-level query operation. These run against MongoDB without custom Python:

```yaml
repositories:
  notes:
    entity: note
    operations:
      published:
        query:
          command: find
          filter: { published: true }
```

Supported `query.command` values are `find`, `findOne`, `aggregate`, `countDocuments`, and `estimatedDocumentCount`. `find`/`findOne`/`countDocuments` require a `filter`; `aggregate` requires a `pipeline`. A repository with no `entity` may set `query.collection` to target a collection explicitly (otherwise `QUERY_MISSING_COLLECTION`). A repository-level operation that has neither `query` nor `handler` fails with `OPERATION_MISSING_QUERY_OR_HANDLER`.

A repository `operations.<op>.handler` is a second handler kind: it is invoked as `await <handler>(**kwargs)` with the call's arguments, rather than receiving a `Request` or `context`. Use the service/controller handler (above) for HTTP-shaped operations and the repository handler for data-access building blocks.

## What the custom operation generates

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/v1/notes/{id}/publish | Custom publish handler |

The full path is `basePath + version + controller base_path + operation path`. With the `api:` block above, `/{id}/publish` under `base_path: /notes` becomes `/api/v1/notes/{id}/publish`.

Custom-operation routes are emitted only by the `fastapi` target. The `raw` target generates CRUD routes only and does not wire custom handlers, so build with the default `fastapi` target when you rely on a handler.

## Key points

- `handler:` on a service operation points to `<alias>.<function>`, resolved through `imports:`.
- Custom operations require `method` and `path` on the controller operation; there is no inference.
- The handler contract differs by target: `request: Request` for the generated FastAPI/raw backend, `context: RequestContext` for `yaml-api run`.
- For a plain parameterized read, prefer a repository `query` operation over a handler.
- Custom operations participate in the same access vocabulary as CRUD; under `run` and `drf` the rules are enforced for custom routes, while the FastAPI custom route leaves enforcement to your handler.

## See Also

- [Handler Context Reference](../Reference/services/handler-context.md) -- the `RequestContext` object and the `run` dev-server handler contract.
- [Custom operations reference](../Reference/services/custom-operations.md) -- the FastAPI/raw `Request` handler contract and import resolution.
