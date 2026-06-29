---
title: "Spec"
description: The full YAML for the organization-membership API with a DTO-typed create body and a request.path.orgId access rule.
---

The full spec. The `dto:` root declares the request shape; the `membership`
controller declares an explicit nested route whose `{orgId}` token is read in the
access rule through `request.path.orgId`.

```yaml
api:
  basePath: /api
  version: v1
  operations:
    auth:
      login: true

dto:
  createMembership:
    fields:
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
      secret: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, format: email }
      password: { type: string, required: true }
      orgId: { type: ref, ref: org, required: true }
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

controllers:
  membership:
    service: membership
    base_path: /orgs/{orgId}/members
    access: "*"
    operations:
      list:
        access: org:*
      create:
        access:
          - org:admin
          - given:
              principal: identity:user
              org: request.path
              member: request.body:createMembership
            when:
              - org.path.orgId equals principal.record.orgId
              - member.body.role not equals 'admin'
```

## Walkthrough

### The DTO validates the body first

`member: request.body:createMembership` binds the request body and validates it
against the `createMembership` DTO before authorization. The DTO requires `role`
to be one of `admin`, `member`, `viewer`. A body that omits `role` or sends an
out-of-set value returns 422 — the rule never runs.

The DTO is a request shape only: it has no `id`, no repository, no route. If you
add `type: id`, `unique`, or `format` to a DTO field, generation fails with
`DTO_FORBIDS_PERSISTENCE_ATTR`.

### The path parameter is read from the route template

The controller's `base_path` is `/orgs/{orgId}/members`, so the composed create
route is `POST /api/v1/orgs/{orgId}/members`. `{orgId}` is an OpenAPI `in: path`
parameter. The rule binds the path map with `org: request.path` and reads the
token in `when:` as `org.path.orgId`.

If you wrote `org.path.tenantId` (a token the route does not declare), generation
would fail with `REQUEST_PATH_PARAM_NOT_DECLARED`.

### The two conditions

```yaml
when:
  - org.path.orgId equals principal.record.orgId
  - member.body.role not equals 'admin'
```

The list form ANDs both. The caller must belong to the organization named in the
URL, and may not assign the `admin` role. An `org:admin` principal skips both
checks via the first rule in the list.

### Why a document rule would not work here

`create` has no fetched record, so a `document:` binding never resolves for it.
The data the rule needs — the path's `orgId` and the body's `role` — lives only on
the request. That is exactly what the request bindings expose. See
[Access control: Request access](../../Reference/controllers/access-control.md).

## Try it

A member of org `acme` adding a viewer to their own org:

```bash
curl -X POST http://localhost:8000/api/v1/orgs/acme/members \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"userId": "u-123", "role": "viewer"}'
```

The same member trying to assign `admin` is denied with 403; a body with an
invalid `role` is rejected with 422 before the rule runs; a member acting on a
different org's URL is denied because `org.path.orgId` does not match their
`principal.record.orgId`.

## See Also

- [DTOs](../../Reference/dto/overview.md)
- [When expressions](../../Reference/when-expressions/overview.md)
- [Access control](../../Reference/controllers/access-control.md)
- [Controller operations](../../Reference/controllers/operations.md)
