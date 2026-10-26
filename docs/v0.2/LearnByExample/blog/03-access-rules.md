---
title: "Access Rules Walkthrough"
description: "How the blog spec's access rules map to roles, ownership, and the URLs they protect."
---

This page walks through the access rules in the blog spec ([Full Spec](./02-spec.md))
rule by rule, and shows the exact URLs each one guards.

> **Enforcement**
>
> Roles, role hierarchies, `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that no rule admits gets 401 when it
> carries no valid credentials and 403 otherwise; a missing record answers 404
> before ownership is checked.

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

Roles are an ordinary `enum` field on the auth entity, named by `auth.roles`, and a
`roles:` block adds their hierarchy. For the blog `user` entity:

```yaml
user:
  extends: base
  type: auth
  auth:
    identifier: email
    via: password
    roles: role
  roles:
    values: [admin, moderator, user]
    default: user
    hierarchy:
      admin: [moderator]
      moderator: [user]
  fields:
    email: { type: string, required: true, unique: true }
    displayName: { type: string, required: true }
    role:
      type: enum
      values: [admin, moderator, user]
      default: user
```

`auth.roles: role` points at the `role` enum field. On every request the role stored
on the user record is loaded into the principal, together with the roles its
hierarchy includes, and compared against the role named in each access rule. A caller
sets the `role` field only to a role it holds: a public `register` always yields
`user`, and only an `admin` can make another user an `admin`.

## Rule-by-rule breakdown

### POST /api/v1/posts (create)

```yaml
create: { access: "*" }
```

Any authenticated user. `"*"` means "any valid principal,
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

Rule 1: any user holding `moderator` passes, which includes every `admin`.
Rule 2: otherwise, if the authenticated user's `sub` matches the post's `authorId`,
allow (the author editing their own post).
If neither rule matches, deny (403). If the post does not exist, the request gets 404
before ownership is checked.

The `given:` map binds symbol names used in the `when` expression. `principal:
identity:user` binds the calling principal and scopes the rule to the `user` identity
collection; `document: posts` loads the route's `posts` record so `document.authorId`
resolves. There are no built-in roots: every symbol a `when:` references must be
declared in `given` (an undeclared root is a build-time error). `principal` and
`document` are conventional names you chose here, not keywords.

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
require the role `admin`. A `moderator` does NOT satisfy `access: admin`: the
hierarchy runs downward only, from `admin` to `moderator` to `user`.

## when-expression syntax

`when:` expressions compare field references and single-quoted string literals using
keywords (not symbols):

- Operators: `equals`, `not equals`, `in`, `not in`, `and`, `or`, `not`.
- Use the word `equals`, never `==`. Keywords are case-insensitive.
- Operands are field references (`principal.sub`, `document.authorId`) or
  single-quoted strings (`'admin'`). There are no boolean literals; parentheses group
  clauses.
- `principal.sub` is the subject id (the JWT `sub`). Stored fields on the
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

1. Does the principal hold `moderator` (directly or as an `admin`)? -> allow.
2. Does `principal.sub` equal `document.authorId`? -> allow.
3. No rule matched -> deny (403).

Put role-only checks first and ownership checks (which fetch the record) after them.
On a missing record, the lookup returns 404 before any ownership rule runs.
