---
title: "Full Spec"
---

This is the complete, buildable spec for the multi-tenant SaaS example. It has two
auth entities (password users and API-key clients), org ownership, and per-operation
ownership rules. Build it with:

```bash
yaml-api build saas.yaml backend -o ./target
# or run it directly against a local MongoDB:
yaml-api run saas.yaml
```

The `api:` block below sets `basePath: /api` and `version: v1`, so every route is
served under `/api/v1/...` (for example `POST /api/v1/users/login`). The two
MongoDB settings are read from `MONGO_URI` / `MONGO_DB` at build time, with the
inline defaults used when those variables are unset.

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
  database: ${MONGO_DB:-saas}

entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  # Human users -- password auth. Each org carries its owner directly (ownerId).
  user:
    extends: base
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  # Machine-to-machine clients -- API key auth with a tier role.
  # `auth.roles: tier` wires the `tier` enum field as this entity's role.
  apiClient:
    extends: base
    type: auth
    auth:
      identifier: clientId
      via: apiKey
      roles: tier
    fields:
      clientId: { type: string, required: true, unique: true }
      name: { type: string, required: true }
      apiKey: { type: string, required: true }
      tier:
        type: enum
        values: [free, premium, enterprise]
        default: free

  org:
    extends: base
    fields:
      name: { type: string, required: true }
      slug: { type: string, required: true, unique: true }
      ownerId: { type: ref, ref: user, required: true }

  resource:
    extends: base
    fields:
      name: { type: string, required: true }
      orgId: { type: ref, ref: org, required: true }
      ownerId: { type: ref, ref: user, required: true }
      data: { type: object }

repositories:
  users:
    entity: user
  apiClients:
    entity: apiClient
  orgs:
    entity: org
  resources:
    entity: resource

services:
  users: {}
  apiClients: {}
  orgs: {}
  resources: {}

controllers:
  users:
    service: users
    base_path: /users
    operations:
      register: { access: public }
      login: { access: public }

  apiClients:
    service: apiClients
    base_path: /api-clients
    access:
      - user:*
    operations:
      create: { access: "user:*" }

  orgs:
    service: orgs
    base_path: /orgs
    access:
      - user:*
      - apiClient:*
    operations:
      create: { access: "user:*" }
      update:
        access:
          - given:
              caller: identity:user
              document: orgs
            when: caller.sub equals document.ownerId
      delete:
        access:
          - given:
              caller: identity:user
              document: orgs
            when: caller.sub equals document.ownerId

  resources:
    service: resources
    base_path: /resources
    access:
      - user:*
      - apiClient:*
    operations:
      create:
        access:
          - user:*
          - apiClient:*
      update: { access: "apiClient:enterprise" }
      delete:
        access:
          - given:
              caller: identity:user
              document: resources
            when: caller.sub equals document.ownerId
```

## Notes on this spec

**Two auth entities require scoped access.** With more than one `type: auth` entity,
a bare role string is rejected as ambiguous (ACCESS_AMBIGUOUS_ROLE). Scope every rule
to an entity: `user:*` and `apiClient:*` allow any authenticated user / any
authenticated client respectively, and `apiClient:enterprise` requires the
`enterprise` tier. Using just `"*"` means any principal of any
auth entity.

**Multiple entity types use a YAML list -- not an inline bracket string.** When a
route must allow more than one entity type, write the rules as a YAML list:

```yaml
access:
  - user:*
  - apiClient:*
```

A quoted string like `access: "[user:*, apiClient:*]"` does NOT work. The brackets are
treated as part of the entity name, and the build fails with ACCESS_UNKNOWN_ENTITY for
every route that uses it.

**Tier roles come from an enum field.** `auth.roles: tier` points the `apiClient`
entity at its `tier` enum field; that is what makes `access: apiClient:enterprise`
meaningful. The standalone entity-level `roles: { values, default, hierarchy }` block
that earlier drafts used is not consumed in v0.2 -- only `auth.roles: <enumField>`
wires a role. New clients get the `tier` field's `default: free` only when the create
payload omits `tier`. Note that tier matching is exact: there is no inheritance, so
`apiClient:enterprise` does not also accept `premium` (see the Enforcement status
note above on hierarchy).

**Ownership rules see only the route's own record.** A rule with `given.caller:
identity:user` plus `given.document: orgs` (or `document: resources`) and
`when: caller.sub equals document.ownerId` reads `document` as the record fetched for
that route (the org for `PATCH /api/v1/orgs/{id}`, the resource for
`DELETE /api/v1/resources/{id}`). There are no built-in roots: both `caller` and
`document` are symbol names this spec declares in `given:` -- `caller` bound to the
authenticated principal (so `caller.sub` is its id) and `document` bound to the route's
collection. The names are arbitrary; an undeclared root would abort generation with
`WHEN_UNBOUND_SYMBOL`. There is no cross-collection lookup: an ownership rule on the
`orgs` controller cannot fetch a separate `memberships` document. That is why this spec
stores ownership directly on each record (`org.ownerId`, `resource.ownerId`) instead of
using a join entity. The record is fetched before the rule runs, so a missing id
returns 404 before any ownership check.

**Document rules are evaluated after the fetch.** Rules that reference `document` (or a
custom document symbol) only run on `get`/`update`/`replace`/`delete`, which load the
record first. `create` has no record to inspect, so it is authorized only by the
entity/role part of the rule (here `user:*` or `apiClient:*`); the server does not
auto-fill `ownerId`, so the client must supply it on create.

**When-expression syntax.** Operands are field references (`caller.sub`,
`document.ownerId`) and single-quoted strings; use the words `equals`, `not equals`,
`and`, `or`, `not`, `in`, `not in` -- never `==`. Stored fields on the caller are read
through `caller.record.<field>` (for example `caller.record.email`); bare `caller`
resolves to the subject id. Avoid custom symbol names that begin with an operator word
(`or`, `in`, `and`, `not`), since the tokenizer reads the leading letters as the
operator -- `caller`, `document`, and `record` are safe.

**Public endpoints in this spec.** The `users` controller sets no controller-level
`access`, so its CRUD routes default to `public`: `GET/POST/PATCH/PUT/DELETE
/api/v1/users` are open. Registration and login are the intended entry points
(`POST /api/v1/users/register`, `POST /api/v1/users/login`), and login returns
`{"token": "...", "user": {...}}` with the password and internal fields stripped. If
you want users locked down, add `access: "*"` (or a stricter rule) to the
`users` controller and keep `register`/`login` `public`.

**API-key clients.** The `apiClient` entity declares a top-level `apiKey` string field;
the generated backend matches an incoming key against that field. Clients send the key
as `X-API-Key: <key>` (or `Authorization: Bearer <key>`) on each request. Be aware that
`apiKey` is returned in CRUD responses, so restrict who can read the `apiClients`
collection -- here only `user:*` can.

**Auth endpoints are opt-in.** `register`/`login` routes are generated only because of
the `api.operations.auth` block above. Login is generated for password entities
(`user`); the API-key `apiClient` gets `register` but no `login` route (clients
authenticate by header, not by exchanging credentials for a token).

**Current limitations to keep in mind.**

- The standalone entity-level `roles:` block is unconsumed; wire roles via
  `auth.roles: <enumField>`.
- Role hierarchy is parsed but not enforced -- only exact role matches apply.
- Access must be a YAML list; the inline bracket-string form is not supported.
- Ownership/`document` rules see only the route's own fetched record; there is no
  cross-collection document fetch.
- `filter`, `writeFields`, and `reason` keys on a rule are accepted but currently
  have no effect.
- `unique: true` is metadata only (no MongoDB index, not enforced on write).
