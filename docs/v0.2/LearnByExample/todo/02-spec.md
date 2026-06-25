---
title: "Full Spec"
description: "The complete todo-app YAML spec, with notes on what each block does and how access is enforced."
---

This is the complete spec for the todo app. It declares an `api:` block so the
routes below are reproducible exactly as written. With `basePath: /api` and
`version: v1`, every route is served under `/api/v1/...`.

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  operations:
    # register/login are NOT generated unless you enable them here
    auth:
      register: true
      login: true

mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-todo}

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
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  list:
    extends: base
    fields:
      name: { type: string, required: true }
      ownerId: { type: ref, ref: user, required: true }

  item:
    extends: base
    fields:
      text: { type: string, required: true }
      done: { type: boolean, default: false }
      doneAt: { type: datetime }
      listId: { type: ref, ref: list, required: true }
      # Denormalized so ownership checks need no item -> list -> user lookup
      ownerId: { type: ref, ref: user, required: true }

repositories:
  users:
    entity: user
  lists:
    entity: list
  items:
    entity: item

services:
  users: {}
  lists: {}
  items: {}

controllers:
  users:
    service: users
    base_path: /users
    # The whole users group is public by default. We expose register/login as
    # public and disable the rest so the resource cannot be browsed or mutated
    # by anonymous callers.
    operations:
      register: { access: public }
      login: { access: public }
      list: false
      get: false
      create: false
      update: false
      replace: false
      delete: false

  lists:
    service: lists
    base_path: /lists
    access: "*"
    operations:
      list: { access: "*" }
      get:
        access:
          - given:
              principal: identity:user
              document: lists
            when: principal.sub equals document.ownerId
      update:
        access:
          - given:
              principal: identity:user
              document: lists
            when: principal.sub equals document.ownerId
      replace:
        access:
          - given:
              principal: identity:user
              document: lists
            when: principal.sub equals document.ownerId
      delete:
        access:
          - given:
              principal: identity:user
              document: lists
            when: principal.sub equals document.ownerId

  items:
    service: items
    base_path: /items
    access: "*"
    operations:
      list: { access: "*" }
      get:
        access:
          - given:
              principal: identity:user
              document: items
            when: principal.sub equals document.ownerId
      update:
        access:
          - given:
              principal: identity:user
              document: items
            when: principal.sub equals document.ownerId
      replace:
        access:
          - given:
              principal: identity:user
              document: items
            when: principal.sub equals document.ownerId
      delete:
        access:
          - given:
              principal: identity:user
              document: items
            when: principal.sub equals document.ownerId
```

## Notes on this spec

**`api.operations.auth` is required for register/login.** `register` and `login`
routes are not generated for an auth entity unless you enable them under
`api.operations.auth`. Without this block, `POST /api/v1/users/register` and
`POST /api/v1/users/login` would not exist, even though the entity is
`type: auth`.

**The `users` controller without overrides is fully public.** A controller's
`operations:` map only overrides routes; it does not pick which routes exist.
The route set comes from the `users` service group, which exposes all six CRUD
operations plus register/login. The `users` controller declares no top-level
`access:`, so its base access is `public`. That means, if you do nothing,
`GET /api/v1/users`, `POST /api/v1/users`, `DELETE /api/v1/users/{id}`, and the
rest are open to anyone. This spec disables them explicitly with `<op>: false`
so only `register` and `login` remain.

**`access: "*"` means any authenticated user.** The `lists` and `items`
controllers use `access: "*"`. Any caller with a
valid token passes the controller-level check; the per-operation `when` rules
then narrow access to the document owner.

**Denormalized `ownerId` on items.** Items store both `listId` (for grouping)
and `ownerId` (for direct access checks). This avoids a two-step lookup
(item -> list -> owner) during authorization.

**`list` is not filtered per document.** The `when` ownership rules apply only to
operations that fetch a single record first: `get`, `update`, `replace`, and
`delete`. The `list` operation returns every document in the collection to any
authenticated caller; it does NOT return only the rows owned by the caller. If
you need an owner-scoped listing, expose it as a custom query operation that
filters by `ownerId`, or keep `list` restricted to trusted callers. The
`access: "*"` on `list` here only requires authentication.

**Create has no ownership check.** There is no post-fetch authorization on
`create` (there is no existing document to check). The client must send an
`ownerId` matching its own `sub`; the server does not auto-fill `ownerId` from
the principal. A caller can therefore create a list or item with someone else's
`ownerId` unless you add validation.

**No admin role.** This app has no privileged roles; access is strictly
ownership-based. To add an admin path later, declare an enum field on the user
entity (for example `role: { type: enum, values: [user, admin], default: user }`)
and point `auth.roles: role` at it, then add `- admin` to the relevant access
lists. The standalone entity-level `roles:` block is parsed but not wired in
v0.2 -- use `auth.roles: <enumFieldName>` instead.

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

## Running it

Save the spec as `todo.yaml` and run it with the in-process dev server:

```sh
yaml-api run todo.yaml
```

The dev server reads its database connection from `YAML_API_MONGO_URI` and
`YAML_API_MONGO_DB` (start MongoDB yourself). Open `http://127.0.0.1:8000/docs`
for the OpenAPI UI.

To generate a deployable FastAPI backend instead:

```sh
yaml-api build todo.yaml -o ./target
```

The backend lands in `./target/backend/`. The generated backend reads
`MONGO_URI` and `MONGO_DB` (note: different variable names from the dev server),
plus the auth settings below.

| Variable               | Read by               | Default                          |
| ---------------------- | --------------------- | -------------------------------- |
| `MONGO_URI`            | generated backend     | `mongodb://localhost:27017`      |
| `MONGO_DB`             | generated backend     | `yaml_api`                       |
| `YAML_API_MONGO_URI`   | `yaml-api run`        | the spec's `mongo.uri`           |
| `YAML_API_MONGO_DB`    | `yaml-api run`        | the spec's `mongo.database`      |
| `JWT_SECRET`           | both                  | dev placeholder (set in prod)    |
| `JWT_EXPIRATION_HOURS` | both                  | `24`                             |
| `PASSWORD_HASH_ROUNDS` | both                  | `390000`                         |

A successful `POST /api/v1/users/login` returns `{"token": "...", "user": {...}}`;
the `user` object has its password, `_id`, and `_auth` fields stripped. Send the
token as `Authorization: Bearer <token>` on subsequent requests.
