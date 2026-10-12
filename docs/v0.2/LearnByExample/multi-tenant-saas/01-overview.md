---
title: "Overview"
description: A SaaS API with two auth entities (human users and machine clients) and per-organization roles stored on a membership join entity.
---

A SaaS API with users, organizations, and per-organization roles. Human users belong
to one or more organizations, with a different role in each. Machine-to-machine
clients authenticate with an API key. Because the spec has two auth entities, every
access rule must name the entity it applies to.

This API block produces all the URLs shown on this page:

```yaml
api:
  basePath: /api
  version: v1
```

So a request to the orgs collection is `GET /api/v1/orgs`, login is
`POST /api/v1/users/login`, and so on.

## Features

- User registration and login with password auth (enabled via `api.operations.auth`)
- Organizations as first-class entities
- Organization membership via a `membership` join entity
- Per-organization roles (`owner`, `admin`, `member`) stored on `membership`, not on the user
- External API clients with API key auth, as a separate auth entity
- Resources scoped to organizations
- Ownership/ABAC `when` rules that compare the request principal against the fetched record

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

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `user` | auth | Human users with password login |
| `apiClient` | auth | Machine-to-machine clients with API key auth |
| `org` | data | An organization (tenant) |
| `membership` | data | User-org relationship carrying the per-org role |
| `resource` | data | A resource scoped to an org |

Each entity is exposed through a repository, and the repository name is the
collection name used in the URL. The shipped spec names them `users`, `apiClients`,
`orgs`, `memberships`, and `resources`, with controllers mounting `apiClients` at
`/api-clients`.

## Auth entities and scoped roles

This app has two auth entities: `user` and `apiClient`. With more than one auth
entity, an unscoped role name is rejected at build time (`ACCESS_AMBIGUOUS_ROLE`), so
every access rule must carry the entity prefix:

```yaml
access: user:*         # any authenticated user
access: apiClient:*    # any authenticated API client
access: user:owner     # a user holding the role 'owner'
```

There are no global user roles in this design. A user's role is org-scoped and lives
on the `membership` record (`owner`, `admin`, `member`), so authorization that
depends on role compares `document.role` on the membership, not a field on the user.

API clients authenticate with the `X-API-Key` header (a bearer token is also
accepted). The matching client is found by comparing the header against the
`apiKey`-style identifier field on the `apiClient` collection.

## Endpoints

All paths assume the `api:` block above (`basePath: /api`, `version: v1`).

### Auth

Register and login exist only because the spec enables them under
`api.operations.auth`. A successful login returns `{"token": "...", "user": {...}}`,
where `user` has its `password`, `_id`, and `_auth` fields stripped.

| Method | Path | Access |
|--------|------|--------|
| POST | /api/v1/users/register | public |
| POST | /api/v1/users/login | public |

### Orgs

| Method | Path | Access |
|--------|------|--------|
| GET | /api/v1/orgs | user:* or apiClient:* |
| GET | /api/v1/orgs/{id} | user:* or apiClient:* |
| POST | /api/v1/orgs | user:* |
| PATCH | /api/v1/orgs/{id} | org owner (membership rule) |
| PUT | /api/v1/orgs/{id} | user:* or apiClient:* |
| DELETE | /api/v1/orgs/{id} | org owner (membership rule) |

### Resources

| Method | Path | Access |
|--------|------|--------|
| GET | /api/v1/resources | user:* or apiClient:* |
| GET | /api/v1/resources/{id} | user:* or apiClient:* |
| POST | /api/v1/resources | user:* or apiClient:* |
| PATCH | /api/v1/resources/{id} | apiClient:enterprise |
| PUT | /api/v1/resources/{id} | user:* or apiClient:* |
| DELETE | /api/v1/resources/{id} | user, ownership rule |

`PUT` (replace) is generated and enabled by default like the other five CRUD
operations; it inherits the controller's `access` unless an `operations.replace`
override narrows it. The `apiClients` and `memberships` collections are also exposed
(create an API client, list and remove memberships) under `/api/v1/api-clients` and
`/api/v1/memberships`.

## Multi-entity access syntax

With two auth entities, allowing more than one entity type requires a YAML list. The
entity prefix is mandatory on every item.

```yaml
access:
  - user:*
  - apiClient:*
```

There is no inline bracket-string form. Writing `access: "[user:*, apiClient:*]"`
does not expand into a list -- it is parsed as a single role string and fails the
build with `ACCESS_UNKNOWN_ENTITY`. Use the list form above.

## Tiered API clients

The spec carries a standalone `roles:` block on `apiClient` (free, premium,
enterprise) with a hierarchy. That entity-level `roles:` block is not consumed in
v0.2, so the tier hierarchy is inert: an `enterprise` client does not automatically
satisfy `access: apiClient:premium`. To make client tiers work as enforced roles,
declare an enum field and point `auth.roles` at it:

```yaml
apiClient:
  type: auth
  auth:
    identifier: clientId
    via: apiKey
    roles: tier
  fields:
    clientId: { type: string, required: true, unique: true }
    name: { type: string, required: true }
    tier:
      type: enum
      values: [free, premium, enterprise]
      default: free
```

A rule like `access: apiClient:enterprise` then matches a client whose `tier` is
exactly `enterprise`. Cross-tier inheritance is not applied (see the enforcement note
above).

## Ownership rules and the document caveat

The `delete` rule on resources uses an ownership `when` expression that compares the
principal against the fetched record:

```yaml
delete:
  access:
    - given:
        principal: identity:user
        document: resources
      when: principal.sub equals document.orgId
```

A document-binding `given` symbol resolves to the record on the route being called.
For `DELETE /api/v1/resources/{id}` the bound document is the resource itself. A rule
cannot fetch a different collection to authorize the current request: binding
`document: memberships` on the orgs controller still evaluates against the org record,
not a membership row. Model ownership with a field on the route's own record (here,
`resource.orgId`), or keep org-level authorization checks on a route that already
loads the relevant document.
