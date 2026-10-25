---
title: "Spec"
description: The full YAML for the organization-membership API with a DTO-typed request binding and a request.path.orgId access rule.
---

The full spec. The `dto:` root declares the request shape; the `memberships`
controller exposes only `create`, on a route whose `{orgId}` token the access rule
reads through `req.path.orgId`.

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

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

entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true, format: email }
      orgId: { type: ref, ref: org }
      role:
        type: enum
        values: [admin, member, viewer]
        default: member

  org:
    fields:
      id: { type: id }
      name: { type: string, required: true }

  membership:
    fields:
      id: { type: id }
      orgId: { type: ref, ref: org, required: true }
      userId: { type: ref, ref: user, required: true }
      role:
        type: enum
        values: [admin, member, viewer]
        required: true
      note: { type: string }

repositories:
  users: { entity: user }
  memberships: { entity: membership }

services:
  users: {}
  memberships: {}

controllers:
  users:
    service: users
    base_path: /users
    access: user:admin
    operations:
      register: { access: public }
      login: { access: public }

  memberships:
    service: memberships
    base_path: /orgs
    operations:
      list: false
      get: false
      update: false
      replace: false
      delete: false
      create:
        path: /{orgId}/members
        access:
          - user:admin
          - given:
              principal: identity:user
              req: request:createMembership
            when:
              - req.path.orgId equals principal.record.orgId
              - req.body.orgId equals req.path.orgId
              - req.body.role not equals 'admin'
```

## Walkthrough

### The DTO validates the body

`req: request:createMembership` binds the whole request and validates its body
against the `createMembership` DTO. The DTO requires `orgId`, `userId`, and a `role`
that is one of `admin`, `member`, `viewer`, and rejects any other key. A body that
omits `role` or sends an out-of-set value returns 422.

The DTO is a request shape only: it has no `id`, no repository, no route. A DTO
field that declares `type: id` or `unique` fails generation with
`SCHEMA_VALIDATION_ERROR`.

### The path parameter is read from the route template

The `create` operation's `path` is `/{orgId}/members` under `base_path: /orgs`, so
the composed route is `POST /api/v1/orgs/{orgId}/members`. `{orgId}` is an OpenAPI
`in: path` parameter, read in `when:` as `req.path.orgId`. A `base_path` itself may
not hold a path token (`CONTROLLER_BASE_PATH_INVALID`).

If you wrote `req.path.tenantId` (a token the route does not declare), generation
would fail with `REQUEST_PATH_PARAM_NOT_DECLARED`.

### The three conditions

```yaml
when:
  - req.path.orgId equals principal.record.orgId
  - req.body.orgId equals req.path.orgId
  - req.body.role not equals 'admin'
```

The list form ANDs them. The caller must belong to the organization named in the
URL, the body must name that same organization, and the caller may not assign the
`admin` role. A `user:admin` principal skips all three through the first rule in
the list.

### Why a document rule would not work here

`create` has no fetched record, so a `document:` binding never resolves for it.
The data the rule needs (the path's `orgId` and the body's `orgId` and `role`)
lives only on the request. That is exactly what the request bindings expose. See
[Access control: Request access](../../Reference/controllers/access-control.md).

### Accounts

Registration is public and takes `orgId` from the body; every other `users` route
requires `user:admin`. A new user's `role` is `member`: a caller sets `role` only
to a role it holds itself.

## Try it

A member of an organization adding a viewer to it:

```bash
curl -X POST "http://localhost:8000/api/v1/orgs/$ORG/members" \
  -u ann@example.com:pw \
  -H "Content-Type: application/json" \
  -d "{\"orgId\": \"$ORG\", \"userId\": \"$USER_ID\", \"role\": \"viewer\"}"
```

The same member trying to assign `admin` gets 403; a body with an invalid `role`
gets 422; a member acting on a different organization's URL, or naming a different
`orgId` in the body, gets 403; a request without credentials gets 401.

## See Also

- [DTOs](../../Reference/dto/overview.md)
- [When expressions](../../Reference/when-expressions/overview.md)
- [Access control](../../Reference/controllers/access-control.md)
- [Controller operations](../../Reference/controllers/operations.md)
