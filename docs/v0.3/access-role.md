# Access-rule `role:`

In v0.3, a long-form access rule can require the principal to hold a role. The
in-process server and generated FastAPI, DRF, and raw-ASGI backends enforce the
same behavior. A v0.2 rule cannot use `role:`.

The `"<entity>:<role>"` shorthand already gates a route on a role, but a
shorthand rule is a bare string with nowhere to put `given:`, `when:` or
`bind:`. A route that must both gate on a role and derive its service inputs
from the principal was therefore inexpressible. `role:` moves the requirement
onto the long rule form, where it composes with the rest of the rule.

## Requiring a role

```yaml
access:
  - given:
      principal: identity:user
    role: org-admin
    bind:
      organizationId: $principal.record.organizationId
```

The rule matches when the caller authenticated as `user` *and* holds
`org-admin`, and then binds the organization from the caller's own record. A
caller without the role falls through to the next rule, and to 403 if none
matches.

`role:` requires an identity binding in `given:` -- the role belongs to the
principal, so a rule with no principal to check is rejected with
`ACCESS_ROLE_WITHOUT_IDENTITY`. The role name must appear in that entity's
declared roles, exactly as for the shorthand form.

Role hierarchies apply: a principal holding a role that includes the required
one matches.

## Scoping a collection to admins

Two rules, one per admitted role, keep the scoping identical while widening who
may read the collection:

```yaml
routes:
  listScoped:
    method: GET
    path: ""
    service: listOrganizationRisks
    access:
      - given:
          principal: identity:user
        role: org-admin
        bind:
          organizationId: $principal.record.organizationId
      - given:
          principal: identity:user
        role: trustiant-admin
        bind:
          organizationId: $principal.record.organizationId
```

Because the organization comes from the principal rather than from a slug, a
member of one organization cannot read another's records even if they hold the
role.

## Errors

| Code | Cause |
| --- | --- |
| `ACCESS_ROLE_UNSUPPORTED` | `role:` used in a spec below version 0.3 |
| `ACCESS_ROLE_WITHOUT_IDENTITY` | `role:` on a rule whose `given:` binds no identity |
| `ACCESS_RULE_INVALID` | the role is not declared by the principal's entity |
