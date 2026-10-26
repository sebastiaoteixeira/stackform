---
title: "Overview"
description: An organization-membership API that authorizes a create against its own request body and a path parameter, using a DTO-typed request binding and request.path.orgId.
---

An organization-membership API that authorizes a `create` against its own request
body and a path parameter — the two things a plain document rule cannot reach on
create.

Members are added under `POST /api/v1/orgs/{orgId}/members`. The route carries a
path parameter (`orgId`, an OpenAPI `in: path` parameter) and a JSON body. The
access rule reads both:

- `req.path.orgId` — the organization the caller is acting on.
- `req.body.orgId` and `req.body.role` — the organization and role being assigned,
  validated against a DTO.

The full spec is on the next page.

> **Enforcement**
>
> Roles, role hierarchies, `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that no rule admits gets 401 when it
> carries no valid credentials and 403 otherwise; a missing record answers 404
> before ownership is checked.

## What this demonstrates

- A top-level `dto:` shape (`createMembership`) that validates the request body.
- A typed whole-request binding: `given: { req: request:createMembership }`, whose
  `req.body` is validated against the DTO and whose `req.path` holds the path
  parameters.
- A path-parameter read in `when:` via `req.path.orgId`, where `orgId` is the
  `{orgId}` token from the route path.
- A `create` rule reasoning about the payload itself, which document rules can never
  do (create has no fetched record).

## The route and its parameters

The `memberships` controller overrides the `create` operation's path to nest the
organization id:

```
POST /api/v1/orgs/{orgId}/members
```

`{orgId}` is an OpenAPI `in: path` parameter. `req.path.orgId` reads exactly this
token; naming a token the route does not declare fails generation with
`REQUEST_PATH_PARAM_NOT_DECLARED`.

## The access rule

```yaml
create:
  path: /{orgId}/members
  access:
    - user:admin                                 # admins assign any role
    - given:
        principal: identity:user
        req: request:createMembership
      when:
        - req.path.orgId equals principal.record.orgId
        - req.body.orgId equals req.path.orgId
        - req.body.role not equals 'admin'
```

Read top-to-bottom:

1. A `user:admin` principal is allowed outright — no body or path inspection.
2. Otherwise the caller must belong to the organization in the path
   (`req.path.orgId equals principal.record.orgId`), the body must name that
   organization (`req.body.orgId equals req.path.orgId`), **and** the caller must
   not be assigning the `admin` role (`req.body.role not equals 'admin'`). The list
   form ANDs the three conditions.

Because `req` binds `request:createMembership`, the body is validated against the
DTO. A body missing `role`, or with a `role` outside the DTO's enum, returns 422.

## The DTO

```yaml
dto:
  createMembership:
    fields:
      orgId: { type: ref, ref: org, required: true }
      userId: { type: ref, ref: user, required: true }
      role:
        type: enum
        values: [admin, member, viewer]
        required: true
      note:
        type: string
        maxLength: 280
```

A DTO is a request shape with validators only — no id, no persistence. See
[DTOs](../../Reference/dto/overview.md). `type: id` and `unique` are rejected inside
a DTO with `SCHEMA_VALIDATION_ERROR`.

## Endpoints

| Method | Path | Access |
|--------|------|--------|
| POST | /api/v1/orgs/{orgId}/members | `user:admin`, or a member of `orgId` assigning a non-admin role in it |
| POST | /api/v1/users/register | public |
| POST | /api/v1/users/login | public |

## See Also

- [DTOs](../../Reference/dto/overview.md)
- [When expressions](../../Reference/when-expressions/overview.md)
- [Access control](../../Reference/controllers/access-control.md)
