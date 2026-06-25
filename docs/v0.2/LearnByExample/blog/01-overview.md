---
title: "Overview"
description: A multi-user blog API with role-based moderation and author-ownership access rules.
---

A multi-user blog API with role-based moderation and author-ownership access rules.

The full spec is on the next page. It declares no `api:` block, so `basePath`
defaults to `/api` and there is no version segment; every route below is served
under `/api/...`. To get versioned URLs like `/api/v1/posts`, add an `api:` block:

```yaml
api:
  basePath: /api
  version: v1
```

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

## Features

- Password login that returns a JWT plus the user record
- Role-based access: `admin`, `moderator`, `user` (matched exactly)
- Public read access for posts and countries
- Authenticated write access with author-ownership rules on posts
- Moderators can edit, replace, delete, or publish any post
- Admin-only writes for the country reference data
- Natural-key country entity to demonstrate `pk:`
- A custom `publish` operation backed by a user-provided handler module

The spec also declares an entity-level `roles: { values, default, hierarchy }`
block on `user`. That block is parsed but not wired in v0.2: it does not assign a
default role on create, and its hierarchy is not applied during enforcement. Roles
are taken from the user record and matched exactly. To attach roles to the auth
entity, use an enum field plus `auth.roles: <fieldName>` (see the roles reference).

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `user` | auth | Site members with `email`/`password` login and a role |
| `post` | data | Blog posts owned by authors |
| `country` | data | Country reference data with a natural key (`pk: code`) |

The `user` and `post` entities extend an abstract `base` that contributes `id` and
`createdAt`. The repositories are named `users`, `posts`, and `countries`; a
repository name is the resource/collection name, so the routes use those names.

## Endpoints

### Auth

Password auth is enabled on `user`, so a login route is generated automatically.

| Method | Path | Access |
|--------|------|--------|
| POST | /api/users/login | public |

Login returns `{"token": "...", "user": {...}}`; the `user` object has `password`,
`_id`, and `_auth` stripped. There is no `/users/register` route: this spec does
not set `api.operations.auth.register`, so registration is not generated. New users
are created through the standard `POST /api/users` create route (which requires
authentication here). To expose a dedicated register endpoint, add:

```yaml
api:
  operations:
    auth:
      register: true
      login: true
```

### Users

The `users` controller sets `access: "*"`, so every CRUD route requires an
authenticated user; `delete` additionally restricts to `admin` or the owner.

| Method | Path | Access |
|--------|------|--------|
| GET | /api/users | `*` (any authenticated user) |
| GET | /api/users/{id} | `*` |
| POST | /api/users | `*` |
| PATCH | /api/users/{id} | `*` |
| PUT | /api/users/{id} | `*` |
| DELETE | /api/users/{id} | `admin` or owner (`principal.sub equals document.id`) |

### Posts

| Method | Path | Access |
|--------|------|--------|
| GET | /api/posts | public |
| GET | /api/posts/{id} | public |
| POST | /api/posts | `*` |
| PATCH | /api/posts/{id} | `moderator` or author |
| PUT | /api/posts/{id} | `moderator` or author |
| DELETE | /api/posts/{id} | `moderator` or author |
| POST | /api/posts/{id}/publish | `moderator` or author |

Author ownership is `principal.sub equals document.authorId`. The `publish` route
is a custom operation: it is emitted by the FastAPI backend and dispatches to the
handler `blog.publish_post`, a module you must provide on the import path. Without
that module the generated app will fail to import the route.

### Countries

`country` uses a natural key (`pk: code`), so the path parameter is the country
code. The controller is `public`, and only `create`, `update`, and `delete` are
overridden to `admin`. The `replace` (PUT) operation is NOT overridden, so it
inherits the controller default and stays public.

| Method | Path | Access |
|--------|------|--------|
| GET | /api/countries | public |
| GET | /api/countries/{code} | public |
| POST | /api/countries | `admin` |
| PATCH | /api/countries/{code} | `admin` |
| PUT | /api/countries/{code} | public (inherited) |
| DELETE | /api/countries/{code} | `admin` |

Because `country` has a natural key, the client supplies `code` in the create body;
there is no server-generated id. Natural keys have no uniqueness index, so creating
two countries with the same `code` inserts two documents rather than returning a
conflict.
