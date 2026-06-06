---
title: "Services Overview"
description: Services are the business-logic layer. Controllers reference services; services reference repositories. Controllers never reference repositories directly.
---

Services are the business-logic layer. Controllers reference services; services reference repositories. Controllers never reference repositories directly.

Each service entry resolves to a set of per-operation units (one per CRUD operation, plus `register`/`login` for auth entities). The generator wires those units into repository methods and HTTP routes. A service you do not declare for a given operation produces no method and no route.

## Forms

```yaml
services:
  # Minified: bind a service group to a repository (the common form)
  myCollection:
    repository: myCollection

  # Empty map: same as above when the service key matches a repository key
  myOtherCollection: {}

  # Per-operation overrides on a repository-backed service
  myCollection:
    repository: myCollection
    operations:
      delete: false                      # disable an operation
      publish: { handler: handlers.publish }  # add a custom operation

  # Explicit single operation (a named delegate)
  list-my-collection: { repository: myCollection, operation: list }
```

## Minified `serviceName: { repository: repoName }`

The primary form binds a service to a repository. The generator expands it into one service unit per resolved CRUD operation, named `<operation>-<serviceName>` internally (for example `list-myCollection`, `create-myCollection`). A controller that references the service group `myCollection` picks those up automatically.

```yaml
services:
  myCollection:
    repository: myCollection
```

## Shorthand `{}`

An empty map is the same as `{ repository: <serviceName> }`: it binds the service to the repository of the same name and enables all resolved CRUD operations.

```yaml
services:
  myCollection: {}
```

The service key must match a repository key of the same name for this shorthand to work. Which operations end up enabled depends on the resolution order below, not on a fixed list:

- Default is all six CRUD operations enabled: `list`, `get`, `create`, `update`, `replace`, `delete`.
- `api.operations.defaults` can disable operations globally (for example `replace: false`).
- `repositories.<name>.crud: [...]` selects the subset that repository exposes.
- `services.<name>.operations.<op>` is the final override (a boolean, or a `{ handler }` map).

Resolution precedence, highest first: service `operations` > repository `crud` > `api.operations.defaults` > all enabled. See [Composable per-operation CRUD](../repositories/composable-crud.md) and [Repository operations](../repositories/operations.md).

## Per-operation overrides

Use `operations:` to disable an operation or attach a custom handler on a repository-backed service:

```yaml
services:
  myCollection:
    repository: myCollection
    operations:
      replace: false                      # disable the PUT operation
      publish: { handler: handlers.publish }
```

Each value is either a boolean (enable/disable) or a `{ handler: <importKey.functionName> }` map for a custom operation. A custom operation declared here is exposed only when the controller also declares its route (see below).

## Custom operations

A custom operation needs two things:

1. A handler on the service: `services.<name>.operations.<op>: { handler: ... }`.
2. A route on the controller: `controllers.<name>.operations.<op>: { method, path }`.

The controller route is required for custom (non-CRUD) operations; without `method` and `path` the build fails with `DESUGAR_CUSTOM_OP_MISSING_ROUTE`.

```yaml
imports:
  handlers: my-app.handlers

services:
  myCollection:
    repository: myCollection
    operations:
      publish: { handler: handlers.publish }

controllers:
  myCollection:
    service: myCollection
    base_path: /my-collection
    operations:
      publish: { method: POST, path: /{id}/publish }
```

With `api: { basePath: /api, version: v1 }` this exposes `POST /api/v1/my-collection/{id}/publish`.

### Handler contract

The handler is a Python function referenced by `importKey.functionName`. In the generated FastAPI and `raw` backends it receives the raw request:

```python
async def publish(request):
    entity_id = request.path_params["id"]
    body = await request.json()
    ...
    return {"id": entity_id, "published": True}
```

The handler does its own data access and owns its response; an uncaught exception becomes a 500. The `yaml-api run` dev server uses a different handler shape (a request-context pipeline step). Both contracts are documented in [Custom operations](custom-operations.md) and [Handler context](handler-context.md).

## Top-level `handler` vs per-operation `handler`

- A top-level `handler` on a service replaces the whole service group with one custom function (no CRUD units are generated for it).
- `operations.<op>.handler` adds a single custom operation alongside the repository-backed CRUD operations.

```yaml
services:
  search: { handler: handlers.search }    # whole-service custom handler

  myCollection:
    repository: myCollection
    operations:
      publish: { handler: handlers.publish }  # one extra operation
```

## Imports

`handler:` values are dotted references of the form `importKey.functionName`. The leading key is looked up in the top-level `imports:` map and the rest is appended; if the key is not declared, the value is treated as a verbatim dotted module path.

```yaml
imports:
  handlers: my-app.handlers            # handlers.publish -> my-app.handlers.publish
```

Declaring the alias in `imports:` keeps handler references short and is recommended, but is not strictly required.

## Repository-level operations as an alternative

Declarative custom reads/writes can also live on the repository instead of the service, via `repositories.<name>.operations.<op>` with a `query: { command, ... }` or a `handler:`. Use the service-level form when the operation is a thin custom HTTP endpoint; use the repository-level form for reusable data operations. See [Repository operations](../repositories/operations.md).

## Auth service operations

Auth entities (`type: auth`) gain `register` and `login` service operations, but only when you enable them under `api.operations.auth`; they are OFF by default.

```yaml
api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

controllers:
  users:
    service: users
    base_path: /users
    operations:
      register: { access: public }
      login: { access: public }
```

With this `api:` block the endpoints are `POST /api/v1/users/register` and `POST /api/v1/users/login`. Marking them `public` matters because, once any `type: auth` entity exists, non-public routes require a valid principal. See [Authentication required by default](../auth/auth-required-by-default.md).

## Example

```yaml
api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

imports:
  handlers: my-app.handlers

services:
  users: {}                              # all CRUD + register/login (auth entity)

  myCollection:
    repository: myCollection
    operations:
      replace: false                     # no PUT
      publish: { handler: handlers.publish }

  # Named single-operation delegate
  list-my-collection: { repository: myCollection, operation: list }
```
