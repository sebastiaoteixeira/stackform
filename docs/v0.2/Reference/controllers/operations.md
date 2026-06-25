---
title: "Controller Operations"
description: Each key under controllers.<name>.operations configures or overrides one HTTP route.
---

Each key under `controllers.<name>.operations` overrides one HTTP route on a
minified controller. The set of routes a controller exposes is decided by the
service group it points at (see "Which operations exist" below); the
`operations:` map only customizes method, path, and access for those routes, or
disables them with `<op>: false`.

## Operation config fields

```yaml
controllers:
  myCollection:
    base_path: /my-collection
    service: myCollection
    access: "*"
    operations:
      create: { access: "*" }
      publish:
        method: POST          # HTTP method
        path: "/{id}/publish" # path relative to base_path
        access: "*" # access rule for this operation
```

For built-in CRUD and auth operations (`list`, `get`, `create`, `update`,
`replace`, `delete`, `register`, `login`) every field is optional and omitted
fields fall back to the defaults below. For custom operations, `method` and
`path` are required (see "Custom operations").

## Default method and path per operation name

| Operation | Default method | Default path |
|-----------|---------------|--------------|
| `list` | GET | `""` |
| `get` | GET | `/{id}` |
| `create` | POST | `""` |
| `update` | PATCH | `/{id}` |
| `replace` | PUT | `/{id}` |
| `delete` | DELETE | `/{id}` |
| `register` | POST | `/register` |
| `login` | POST | `/login` |
| custom | required (no default) | required (no default) |

The default path for `list` and `create` is the empty string `""`, not `/`.
The full URL of a route is composed as:

```
api.basePath + [ "/" + api.version ] + controller.base_path + operation path
```

`api.basePath` defaults to `/api`, and `api.version` adds a segment only when
you set it. So with this `api:` block:

```yaml
api:
  basePath: /api
  version: v1
```

a `myCollection` controller whose `base_path` is `/my-collection` generates:

- `GET    /api/v1/my-collection`            (list)
- `POST   /api/v1/my-collection`            (create)
- `GET    /api/v1/my-collection/{id}`       (get)
- `PATCH  /api/v1/my-collection/{id}`       (update)
- `PUT    /api/v1/my-collection/{id}`       (replace)
- `DELETE /api/v1/my-collection/{id}`       (delete)

The `{id}` segment is always the literal string `{id}`; it is not renamed to
the entity's primary-key field. The generated path parameter is always called
`id`, even for entities that use a natural key via `pk:`.

## Which operations exist

You do not enable routes here. A minified controller exposes a route for each
operation present in its service group, and the service group's operations are
resolved as:

```
service operations override > repository crud list > api.operations.defaults > all six enabled
```

All six CRUD operations (`list`, `get`, `create`, `update`, `replace`,
`delete`) are enabled by default. To remove one, list a subset in the
repository's `crud:` field or disable it under `api.operations.defaults`:

```yaml
repositories:
  myCollection:
    entity: myEntity
    crud: [list, get, create]   # no update/replace/delete -> no PATCH/PUT/DELETE route

api:
  operations:
    defaults:
      replace: false            # turn PUT off for every controller
```

See `../repositories/composable-crud.md` for the full resolution model.

## Disabling an operation on one controller

Setting an operation to `false` removes that route from this controller only,
even when the service group still exposes it:

```yaml
controllers:
  myCollection:
    base_path: /my-collection
    service: myCollection
    operations:
      delete: false   # no DELETE /api/v1/my-collection/{id} on this controller
```

Omitting an operation from the `operations:` map does NOT disable it: the route
is still generated, using the default method, path, and the controller's
`access` value. Disabling is explicit (`<op>: false`) or done upstream through
the repository `crud:` list / `api.operations.defaults`.

## Access shorthand

Single-value access can use the inline object form:

```yaml
operations:
  create: { access: "*" }
  list: { access: public }
  update: { access: editor }
```

The access vocabulary is:

- `public` -- no authentication required.
- `"*"` -- any authenticated principal.
- `<entity>:*` -- any principal from that auth entity.
- `<entity>:<role>` -- a principal of that entity holding that role.
- bare `<role>` -- shorthand for `<entity>:<role>` when exactly one auth
  entity exists; ambiguous with more than one (ACCESS_AMBIGUOUS_ROLE), and an
  error without any auth entity (ACCESS_NO_AUTH_ENTITY).

A minified controller with no `access:` defaults to `public`. If you intend a
controller to be protected, set `access:` explicitly; an omitted `access:`
silently makes every operation public.

> **Watch out**
>
> Routes are only actually protected once at least one `type: auth` entity
> exists in the spec. With no auth entity in the spec, even non-`public` routes
> stay open.

## Auth operations are off by default

`register` and `login` routes are not generated unless you enable them under
`api.operations.auth`. They are only valid for a service backed by a `type:
auth` entity:

```yaml
api:
  operations:
    auth:
      register: true
      login: true

controllers:
  myAuthCollection:
    base_path: /my-auth-collection
    service: myAuthCollection
    access: "*"
    operations:
      register: { access: public }   # POST /api/v1/my-auth-collection/register
      login: { access: public }      # POST /api/v1/my-auth-collection/login
```

## Custom operations

A custom operation (any name that is not a built-in CRUD or auth op) requires
both `method:` and `path:`; there is no inference. Omitting either fails
generation with DESUGAR_CUSTOM_OP_MISSING_ROUTE:

```yaml
operations:
  publish:
    method: POST
    path: "/{id}/publish"     # -> POST /api/v1/my-collection/{id}/publish
    access: "*"
```

A custom route is only emitted when the service group actually has a backing
operation of that name (a service whose key is `<op>-<service>`, declared via
the repository's `operations.<op>` block with a `query` or `handler`). Without
a backing service operation, the custom op produces no route. See
`../services/custom-operations.md` and `../repositories/operations.md`.

## Access with conditional (ABAC) rules

For ownership or other record-conditional access, give `access:` a list. Each
list item is either a role/keyword string or a rule object. A rule object binds
`given:` symbols and tests them with a `when:` expression; `then:` chooses the
effect and defaults to `allow`:

```yaml
operations:
  update:
    access:
      - admin                         # admins always allowed
      - given:
          principal: identity:myEntity # bind the caller's principal
          document: myCollection      # bind the fetched document
        when: principal.sub equals document.ownerId
        then: allow
```

Notes on the rule object:

- `given:` keys are symbol names you choose. A value of `identity:<entity>`
  binds the principal; any other value is a document binding
  (`<collection>` or `<collection> by <param>`). The names `principal` and
  `document` are also auto-bound inside `when:` when referenced.
- `when:` uses words, not operators: `equals`, `not equals`, `and`, `or`,
  `not`, `in`, `not in`. Operands are field references (for example
  `document.ownerId`) and single-quoted string literals. Stored fields on the
  caller are read via `principal.record.<field>`.
- Rules needing a document are evaluated after the record is fetched; a missing
  record returns 404 before any ownership check. `create` has no document, so
  it is authorized before insert (role/keyword rules only). See
  `access-control.md` for full evaluation order.

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
