---
title: "Overview"
description: An organization-membership API that authorizes a create against its own request body and a path parameter, using a DTO-typed body and request.path.orgId.
---

An organization-membership API that authorizes a `create` against its own request
body and a path parameter — the two things a plain document rule cannot reach on
create.

Members are added under `POST /api/v1/orgs/{orgId}/members`. The route carries a
path parameter (`orgId`, an OpenAPI `in: path` parameter) and a JSON body. The
access rule reads both:

- `req.path.orgId` — the organization the caller is acting on.
- `req.body.role` — the role being assigned, validated against a DTO.

The full spec is on the next page.

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

## What this demonstrates

- A top-level `dto:` shape (`createMembership`) used to validate the request body
  before authorization runs.
- A typed body binding: `given: { member: request.body:createMembership }`.
- A path-parameter binding read in `when:` via `req.path.orgId`, where `orgId` is
  the `{orgId}` token from the route path.
- The create gap closed: a `create` rule reasoning about the payload itself, which
  document rules can never do (create has no fetched record).

## The route and its parameters

The `membership` controller declares an explicit `create` route under a base path
that nests the organization id:

```
POST /api/v1/orgs/{orgId}/members
```

`{orgId}` is an OpenAPI `in: path` parameter. `request.path.orgId` reads exactly
this token; naming a token the route does not declare fails generation with
`REQUEST_PATH_PARAM_NOT_DECLARED`.

## The access rule

```yaml
create:
  access:
    - org:admin                                  # org admins assign any role
    - given:
        principal: identity:user
        org: request.path
        member: request.body:createMembership
      when:
        - org.path.orgId equals principal.record.orgId
        - member.body.role not equals 'admin'
```

Read top-to-bottom:

1. An `org:admin` principal is allowed outright — no body or path inspection.
2. Otherwise the caller must belong to the organization in the path
   (`org.path.orgId equals principal.record.orgId`) **and** must not be assigning
   the `admin` role (`member.body.role not equals 'admin'`). The list form ANDs the
   two conditions.

Because `member` binds `request.body:createMembership`, the body is validated
against the DTO **before** the rule runs. A body missing `role`, or with a `role`
outside the DTO's enum, returns 422 — the access rule never executes.

## The DTO

```yaml
dto:
  createMembership:
    fields:
      role:
        type: enum
        values: [admin, member, viewer]
        required: true
```

A DTO is a request shape with validators only — no id, no persistence. See
[DTOs](../../Reference/dto/overview.md). `type: id`, `unique`, and `format` are
rejected inside a DTO with `DTO_FORBIDS_PERSISTENCE_ATTR`.

## Endpoints

| Method | Path | Access |
|--------|------|--------|
| POST | /api/v1/orgs/{orgId}/members | `org:admin`, or an org member assigning a non-admin role |
| GET | /api/v1/orgs/{orgId}/members | `org:*` |

## See Also

- [DTOs](../../Reference/dto/overview.md)
- [When expressions](../../Reference/when-expressions/overview.md)
- [Access control](../../Reference/controllers/access-control.md)
