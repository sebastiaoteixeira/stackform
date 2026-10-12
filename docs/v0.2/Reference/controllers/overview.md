---
title: "Controllers Overview"
description: Controllers bind services to HTTP methods and paths, set the route prefix, and declare who may call each operation.
---

Controllers bind services to HTTP methods and paths, set the route prefix, and declare who may call each operation. A controller is the HTTP face of a service group: it decides which operations are exposed, under what URLs, and with what access rules.

## Structure

A controller can be written in minified form, where you name a `service` and let the engine expand standard operations into routes:

```yaml
controllers:
  my-collection:
    service: my-collection       # service group name
    base_path: /my-collection
    access: "*"                  # default for all operations (omit -> public)
    operations:
      register: { access: public }
      login: { access: public }
      delete: false              # disable this operation entirely
```

Each operation entry may be:

- `false` to disable the operation (no route is generated).
- a map with any of `method`, `path`, and `access` to override the route.

## Fields

### `service`

Type: string (service group name). Required for minified controllers.

The service group this controller routes to. The engine looks for expanded service operations named `<op>-<service>` (for example `list-my-collection`, `create-my-collection`). Standard CRUD and auth operations are matched automatically; a route is only generated for an operation that has a backing service.

### `base_path`

Type: string. Optional. Default: `""`.

URL prefix for all routes in this controller. The full URL is composed as:

```
{api.basePath}[/{api.version}] + base_path + <operation suffix>
```

With `api: { basePath: /api, version: v1 }` and `base_path: /my-collection`, the list route is `GET /api/v1/my-collection` and the get route is `GET /api/v1/my-collection/{id}`.

### `access`

Type: access value (see [access-control](./access-control.md)). Optional. Default: `public`.

Default access rule applied to every operation. Individual operations override it with their own `access`. If you omit `access` on a minified controller, every operation defaults to `public`, so an entity is only protected once you set a non-public value. Protection is wired only when an identity entity (a `type: auth` entity) exists; with no auth entity in the spec, even non-public routes stay open.

> **Enforcement status**
>
> Roles (exact match), `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

### `operations`

Type: map. Optional.

Per-operation configuration. Keys are operation names: the standard CRUD ops (`list`, `get`, `create`, `update`, `replace`, `delete`), the auth ops (`register`, `login`), or a custom operation name.

Each operation value can be:

- `false` to disable the operation (the route is not generated).
- a map with `method:`, `path:`, and/or `access:` to override the route.

Omitting an operation from this map does NOT disable it. The set of routes comes from the service group (the repository `crud` selection plus `api.operations.defaults`); `operations` only overrides or disables what already exists.

## Default routes for standard operations

When `method:` and `path:` are not specified, the engine uses these conventions:

| Operation | Method | Path suffix |
|-----------|--------|-------------|
| `list` | GET | `""` (the `base_path` itself) |
| `get` | GET | `/{id}` |
| `create` | POST | `""` (the `base_path` itself) |
| `update` | PATCH | `/{id}` |
| `replace` | PUT | `/{id}` |
| `delete` | DELETE | `/{id}` |
| `register` | POST | `/register` |
| `login` | POST | `/login` |

`register` and `login` are only generated for services backing a `type: auth` entity, and only when enabled via `api.operations.auth` (off by default).

`{id}` is always the literal segment `{id}`; the path parameter is always named `id` regardless of the entity's primary-key field name.

## Disabling and overriding operations

Disable an operation with `<op>: false`:

```yaml
controllers:
  my-collection:
    service: my-collection
    base_path: /my-collection
    operations:
      delete: false             # no DELETE route is generated
```

Override the method, path, or access of an operation by giving it a map:

```yaml
controllers:
  my-collection:
    service: my-collection
    base_path: /my-collection
    operations:
      list: { access: public }
      update: { access: "*" }
```

## Access values

The `access` value selects who may call an operation:

- `public` - no authentication required.
- `"*"` - any authenticated principal.
- `<entity>:*` - any principal from that auth entity.
- `<entity>:<role>` - a principal from that entity holding the role (exact match).
- `<role>` - shorthand for the single auth entity in the spec; ambiguous (ACCESS_AMBIGUOUS_ROLE) when more than one auth entity exists, and an error (ACCESS_NO_AUTH_ENTITY) when there is none.
- a list of rules, including ABAC `given`/`when` rules.

See [access-control](./access-control.md) for the full rule grammar.

## Custom operations

A custom operation has no route convention, so it must declare both `method` and `path`, and a backing service operation (`<op>-<service>`) must exist (defined under `services` / `repositories`). Otherwise generation fails with DESUGAR_CUSTOM_OP_MISSING_ROUTE.

```yaml
api:
  basePath: /api
  version: v1

controllers:
  my-collection:
    service: my-collection
    base_path: /my-collection
    access: public
    operations:
      create: { access: "*" }
      activate:
        method: POST
        path: "/{id}/activate"
        access: "*"
```

This exposes `POST /api/v1/my-collection/{id}/activate`, gated to any authenticated principal.

## Explicit routes form

A controller may also list its routes explicitly instead of relying on the minified `service` form. Each route names the expanded service operation, its method, path, and access:

```yaml
controllers:
  users:
    base_path: /users
    routes:
      list:
        service: list-users
        method: GET
        path: ""
        access: "*"
      login:
        service: login-users
        method: POST
        path: /login
        access: public
```

The minified `service` form is sugar that expands to this `routes` form during generation.

## Example

```yaml
api:
  basePath: /api
  version: v1

controllers:
  users:
    service: users
    base_path: /users
    access: "*"
    operations:
      register: { access: public }
      login: { access: public }
      delete:
        access:
          - given:
              principal: identity:user
              document: users
            when: principal.sub equals document.id

  my-collection:
    service: my-collection
    base_path: /my-collection
    access: public
    operations:
      create: { access: "*" }
      activate:
        method: POST
        path: "/{id}/activate"
        access: "*"
```

With this `api:` block the user routes are `GET /api/v1/users`, `POST /api/v1/users/register`, `POST /api/v1/users/login`, `DELETE /api/v1/users/{id}` (owner-only), and the my-collection routes include `POST /api/v1/my-collection` (any authenticated principal) and `POST /api/v1/my-collection/{id}/activate`.
