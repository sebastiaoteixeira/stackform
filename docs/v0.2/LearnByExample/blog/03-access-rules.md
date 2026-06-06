---
title: "Access Rules Walkthrough"
description: "How the blog spec's access rules map to roles, ownership, and the URLs they protect."
---

This page walks through the access rules in the blog spec ([Full Spec](./02-spec.md))
rule by rule, and shows the exact URLs each one guards.

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

## URLs in this walkthrough

The spec does not set an `api:` block, so `basePath` defaults to `/api` and no
version segment is emitted. To get the versioned paths shown below, add an `api:`
block to the spec:

```yaml
api:
  basePath: /api
  version: v1
```

With that block, every route is prefixed with `/api/v1`. The walkthrough uses those
prefixed URLs (for example `PATCH /api/v1/posts/{id}`). Without the `version`, drop
the `/v1` segment (`PATCH /api/posts/{id}`).

## How roles are defined

Roles are an ordinary `enum` field on the auth entity, named by `auth.roles`. There
is no separate roles block to enable them. For the blog `user` entity:

```yaml
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
```

`auth.roles: role` points at the `role` enum field. At login, the role stored on the
user record is loaded into the principal and compared (exact match) against the role
named in each access rule. A new user gets a role only through the enum field's
`default:` -- the `role` field is otherwise stripped from create/update payloads, so
clients cannot self-assign a role.

An entity-level `roles: {values, default, hierarchy}` block (separate from the field)
is not wired in v0.2: the schema accepts it but the transformer ignores it. Define
roles via the enum field plus `auth.roles` as shown above.

## Rule-by-rule breakdown

### POST /api/v1/posts (create)

```yaml
create: { access: "*" }
```

Any authenticated user. `"*"` (alias `authenticated`) means "any valid principal,
regardless of role." Anonymous requests get 401.

### PATCH /api/v1/posts/{id} (update)

```yaml
update:
  access:
    - moderator
    - given:
        principal: identity:user
        document: posts
      when: principal.sub equals document.authorId
```

Rule 1: any user whose `role` is exactly `moderator` passes.
Rule 2: otherwise, if the authenticated user's `sub` matches the post's `authorId`,
allow (the author editing their own post).
If neither rule matches, deny (403). If the post does not exist, the request gets 404
before ownership is checked.

The `given:` map binds symbol names used in the `when` expression. `principal:
identity:user` binds the calling principal and scopes the rule to the `user` identity
collection; `document: posts` loads the route's `posts` record so `document.authorId`
resolves. The built-in `principal` and `document` roots are available even without
`given`, but `given` lets you name and scope them explicitly.

### DELETE /api/v1/users/{id}

```yaml
delete:
  access:
    - admin
    - given:
        principal: identity:user
        document: users
      when: principal.sub equals document.id
```

Rule 1: an `admin` can delete any user.
Rule 2: a user can delete their own account (`sub` equals the user document's `id`).

### POST /api/v1/posts/{id}/publish (custom operation)

```yaml
publish:
  method: POST
  path: "/{id}/publish"
  access:
    - moderator
    - given:
        principal: identity:user
        document: posts
      when: principal.sub equals document.authorId
```

Same pattern as update: a `moderator`, or the owning author. Custom operations must
declare both `method` and `path`; the route is `POST /api/v1/posts/{id}/publish`.

### Countries (admin-only writes)

```yaml
create: { access: admin }
update: { access: admin }
delete: { access: admin }
```

Reads are `public` (inherited from the controller-level `access: public`). Writes
require the exact role `admin`. A `moderator` does NOT satisfy `access: admin`: only
exact role matches are enforced, so there is no inheritance from `admin` down to
`moderator` or up from `moderator` to `admin`.

## when-expression syntax

`when:` expressions compare field references and single-quoted string literals using
keywords (not symbols):

- Operators: `equals`, `not equals`, `in`, `not in`, `and`, `or`, `not`.
- Use the word `equals`, never `==`. Keywords are case-insensitive.
- Operands are field references (`principal.sub`, `document.authorId`) or
  single-quoted strings (`'admin'`). There are no boolean literals and no parentheses
  grouping.
- `principal` alone resolves to the subject id (the JWT `sub`). Stored fields on the
  authenticated user are read through `principal.record.<field>` (for example
  `principal.record.email`).
- `document.<field>` reads the fetched route record.

Examples:

```yaml
when: principal.sub equals document.authorId
when: document.status in ['draft', 'review']
when: principal.record.email not equals 'banned@example.com'
```

A `when:` value may also be a YAML list of strings, which are AND-ed together:

```yaml
when:
  - principal.sub equals document.authorId
  - document.status not equals 'archived'
```

### Custom symbol names and document binding

Symbol names under `given:` are arbitrary -- `principal`/`document` are conventional,
not required. You may name a document binding and reference it by that name, and you
may bind a document by an explicit path parameter with `<collection> by <param>`:

```yaml
access:
  - given:
      author: identity:user
      post: posts by id
    when: author.sub equals post.authorId
```

Here `author` and `post` are the symbol names used in `when`; `posts by id` loads the
`posts` record identified by the `{id}` path parameter.

## ABAC evaluation order

Rules in an `access:` list are evaluated top to bottom; the first matching rule wins.
For the posts update rule:

1. Is the principal's role exactly `moderator`? -> allow.
2. Does `principal.sub` equal `document.authorId`? -> allow.
3. No rule matched -> deny (403).

Put role-only checks first and ownership checks (which fetch the record) after them.
On a missing record, the lookup returns 404 before any ownership rule runs.
