---
title: "Tutorial 07: ABAC Rules"
description: Attribute-based access control with given/when/then -- compare the request principal against the document being accessed.
---

**Concept introduced:** Attribute-based access control (ABAC) with `given`/`when`/`then` -- document-level rules that compare the authenticated user against the record being accessed.

ABAC is access control based on attributes of the request, the authenticated user (the *principal*), and the document being accessed.

A key concept used throughout ABAC rules is `principal.sub`. The `sub` (short for "subject") is the authenticated user's primary-key value -- their `id`. It is available on every authenticated request and is the main way to compare "who is making this request" against "who owns this document."

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

## Authors can edit their own notes

Role-based rules cover broad access (e.g., all moderators can edit any note), but they cannot express "only the author can edit their own note." ABAC rules solve this by comparing attributes of the authenticated user against attributes of the document being accessed.

Roles come from an enum field referenced by `auth.roles`. The standalone entity-level `roles:` block (with `values`/`default`/`hierarchy`) is not wired in v0.2 -- declare an `enum` field and point `auth.roles` at it instead.

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  note:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }
      authorId: { type: ref, ref: user }

repositories:
  users:
    entity: user
  notes:
    entity: note

services:
  users: {}
  notes: {}

controllers:
  users:
    service: users
    base_path: /users
    access: public
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
```

With `api: { basePath: /api, version: v1 }`, the routes are `PATCH /api/v1/notes/{id}` and `DELETE /api/v1/notes/{id}`. A moderator may edit or delete any note; any other authenticated user may edit or delete only notes where `authorId` matches their own `sub`.

Two notes about this spec:

- `register` and `login` are not generated unless you enable them. The minified `users` controller above lists them under `operations:`, which generates `POST /api/v1/users/register` and `POST /api/v1/users/login`.
- A minified controller defaults to `access: public`. Setting `access: public` here is explicit; the per-operation rules on `create`/`update`/`delete` override it for those operations.

## How given/when/then works

Each item in the `access:` list is evaluated top-to-bottom. The first matching rule wins.

```yaml
access:
  - moderator                           # rule 1: allow moderators (exact role match)
  - given:
      principal: identity:user          # bind the authenticated user under "principal"
      document: notes                   # load the target document under "document"
    when: principal.sub equals document.authorId   # condition
    # then: allow                       # default when omitted
```

Key terms:

- `identity:user` -- The `identity:` prefix tells the system this is an auth-entity principal. The value after the colon is the entity name.
- `principal` -- the symbol name you bind the authenticated user to. The name is arbitrary; `principal` is just a convention. You can name it anything (for example `editor: identity:user`) and then reference `editor.sub` in the `when`.
- `document: notes` -- the **repository name** (the collection), not the entity name. The system fetches the target document from this collection to evaluate the rule.
- `then: allow` is the default. Write `then: deny` to invert the effect.

If no rule matches, the request is denied (403).

### Binding the document by a different parameter

By default `document: notes` loads the record addressed by the route's `{id}`. To load a document keyed by a different path parameter, use the `<collection> by <param>` form:

```yaml
given:
  principal: identity:user
  parent: posts by postId
when: principal.sub equals parent.authorId
```

## Deny pattern: block non-authors from updating

```yaml
update:
  access:
    - admin
    - given:
        principal: identity:user
        document: notes
      when: principal.sub not equals document.authorId
      then: deny
    - then: allow
```

Rule sequence: admin passes first. Non-authors match the `then: deny` rule and are forbidden. Everyone else (the author) reaches the final `then: allow`.

## When expression syntax

```yaml
when: principal.sub equals document.authorId
when: principal.record.role equals 'admin'
when: principal.record.role in ['admin', 'moderator']
when: document.status not in ['deleted', 'archived']
when: principal.sub equals document.authorId or principal.record.role equals 'admin'
```

Operands and references:

- `principal.sub` -- the principal's unique identifier (primary-key value). Bare `principal` (with no field) also resolves to `sub`.
- `principal.record.fieldName` -- any stored field on the authenticated user's record. Use `principal.record.<field>`, not `principal.<field>`.
- `document.fieldName` -- any field on the document being accessed.

Operators: `equals`, `not equals`, `in`, `not in`, `and`, `or`, `not`. The right-hand side of a comparison is either another field reference or a single-quoted string. Use the words (`equals`), not symbols (`==`). String values must be wrapped in single quotes; `in`/`not in` take a bracketed list of single-quoted strings. There is no parenthesis grouping; combine conditions with `and`/`or`/`not`.

A `when:` value may also be a YAML list of expressions, which are AND-ed together:

```yaml
when:
  - principal.sub equals document.authorId
  - document.status not in ['archived']
```

**Note:** On `create` operations there is no existing document yet, so rules with `document:` bindings cannot run a post-fetch check. Use principal-only rules (role checks, `authenticated`/`*`) to control create access. The example above guards `create` with `access: "*"` (any authenticated user).

## Accepted but not yet enforced

The optional `filter:`, `writeFields:`, and `reason:` keys on a rule object are parsed and validated, but do not change enforcement today. Treat them as forward-looking metadata; access is decided solely by principal match, role match, and the `when` condition.

## Key points

- Rules are evaluated in order. Put broad role rules first, document-specific rules after.
- `document:` in `given:` references the repository (collection) name (`notes`), not the entity name.
- `given:` symbol names are arbitrary; `principal`/`document` are conventions, not reserved words.
- `then: deny` combined with a fallback `then: allow` is a common pattern for inverse logic.
- Roles are an enum field selected by `auth.roles`; only exact role matches are enforced (hierarchy is inert today).
