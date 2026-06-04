---
title: "Full Spec"
description: "The complete, reproducible blog YAML spec, with notes on what each block does and how it is enforced."
---

This is the full blog spec. It compiles with `yaml-api build` and runs with
`yaml-api run`. Copy it verbatim and follow the run notes at the bottom to
reproduce every URL shown in the rest of this track.

The `api:` block below sets `basePath: /api` and `version: v1`, so every route
is served under `/api/v1/...` (for example `POST /api/v1/users/login`). Change
those two values and all URLs shift accordingly.

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

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-blog}

# Abstract base provides id and createdAt to all entities
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
      # Roles come from an enum field named here; the field must exist below.
      roles: role
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  post:
    extends: base
    fields:
      title: { type: string, required: true }
      content: { type: string }
      authorId: { type: ref, ref: user }
      published: { type: boolean, default: false }
      publishedAt: { type: datetime }
      tags:
        type: array
        items:
          type: string

  # Natural key: country code is the primary key, no auto-generated id
  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string, required: true }

# Optional: role hierarchy is parsed and reaches the React RBAC matrix, but it is
# NOT applied during access enforcement today (only exact role matches count).
roles:
  user:
    admin: [moderator]
    moderator: [user]

repositories:
  users:
    entity: user
  posts:
    entity: post
  countries:
    entity: country

services:
  users: {}
  posts:
    operations:
      publish: { handler: blog.publish_post }
  countries: {}

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
          - admin
          - given:
              principal: identity:user
              document: users
            when: principal.sub equals document.id

  posts:
    service: posts
    base_path: /posts
    access: public
    operations:
      create: { access: "*" }
      update:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
      replace:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
      delete:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
      publish:
        method: POST
        path: "/{id}/publish"
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId

  countries:
    service: countries
    base_path: /countries
    access: public
    operations:
      create: { access: admin }
      update: { access: admin }
      replace: { access: admin }
      delete: { access: admin }
```

## Reading the spec

- Entities and inheritance. `base` is `abstract: true`, so it never becomes a
  collection; its `id` and `createdAt` fields are flattened into `user` and
  `post` at build time. `country` uses `pk: code` instead, so it has a natural
  string key and no auto-generated id (the client supplies `code` on create).

- Roles. The working mechanism is `auth.roles: role` plus an enum field named
  `role` (with `values` and a `default`). The role is read from that field at
  request time; new users get `user` from the field's `default`. A standalone
  entity-level `roles: { values, default, hierarchy }` block is silently ignored
  by v0.2 -- do not use it. The top-level `roles:` map keyed by the auth entity
  name (`user`) is parsed and feeds the React RBAC matrix, but hierarchy is not
  yet applied during enforcement.

- Repositories and CRUD. All six CRUD operations (list, get, create, update,
  replace, delete) are enabled by default, so none of these repositories needs a
  `crud:` list. To expose a subset, add `crud: [list, get]` (read-only) on the
  repository; to disable one operation globally, use
  `api.operations.defaults: { replace: false }`. There is no boolean
  `operations:` toggle on a repository -- `repositories.<name>.operations` is
  only for custom `query`/`handler` ops.

- Auth endpoints. `login` is always generated for a password identity (here
  `POST /api/v1/users/login`). `register` is off unless you enable it; the
  `api.operations.auth: { register: true }` above turns the `create` route into a
  public `POST /api/v1/users/register` that reuses the create pipeline. The login
  response is `{ "token": "...", "user": { ... } }`, with `password`, `_id`, and
  `_auth` stripped from the returned user. The JWT carries only the subject id and
  the identity collection name; roles are re-read from the database per request.

- Access on writes. Every controller is `public` by default, so each write that
  should be protected is overridden explicitly. `posts.create` is `"*"` (any
  authenticated user). `update`, `replace`, `delete`, and the custom `publish` op
  allow either a `moderator` or the post's own author (the ownership rule binds
  the route's document and compares `principal.sub equals document.authorId`).
  `countries` writes are admin-only on all four mutating ops, including `replace`
  (PUT) -- without that override PUT would inherit the controller's `public`
  access.

- The custom `publish` operation. It is declared on the service as
  `publish: { handler: blog.publish_post }` and wired to a route by the controller
  (`method` and `path` are required for a custom op). At runtime the handler is
  your own module: provide a `blog.py` next to the spec exposing
  `async def publish_post(request)`. Note that custom-handler routes are emitted by
  the `yaml-api run` dev server; the generated FastAPI backend (the default `build`
  target) does not yet emit a route for a custom service handler, so use `run` for
  the `publish` endpoint until that lands.

- Declarative-only fields. `unique: true` on `email` documents intent and drives
  the UI, but it is not enforced: no MongoDB index is created and duplicate emails
  are not rejected on write. Enforce uniqueness in your own handler if you need it.

- Environment interpolation. `${MONGO_URI:-mongodb://localhost:27017}` and
  `${MONGO_DB:-blog}` are resolved per string scalar before validation. The
  `:-default` form supplies a fallback; a bare `${VAR}` with no value set aborts
  the build with `Environment variable 'VAR' is required`.

## Build and run

Run the in-process dev server (full access enforcement, custom handler routes,
auto-reload on restart):

```bash
YAML_API_MONGO_URI=mongodb://localhost:27017 \
YAML_API_MONGO_DB=blog \
yaml-api run blog.yaml
```

Generate a standalone FastAPI backend instead:

```bash
yaml-api build blog.yaml backend -o ./target
```

The dev server reads `YAML_API_MONGO_URI` / `YAML_API_MONGO_DB`; the generated
backend reads `MONGO_URI` / `MONGO_DB` (with `JWT_SECRET` and
`JWT_EXPIRATION_HOURS` for tokens). Open `http://127.0.0.1:8000/docs` to explore
the API.
