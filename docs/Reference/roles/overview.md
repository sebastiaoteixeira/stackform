# Reference: Roles Overview

The top-level `roles:` section defines role hierarchy relationships for auth entities.

## Structure

```yaml
roles:
  entityName:
    roleName: [includedRole1, includedRole2]
```

Each key under `roles:` is an auth entity name. Under each entity, keys are role names and values are lists of roles that are included (inherited) by that role.

## Example

```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
```

This declares that:
- `admin` includes `moderator`
- `moderator` includes `user`
- Inclusion is transitive: `admin` also includes `user`

## Relationship to entities

The `roles:` section is separate from entity declaration. The entity declares which field holds the role:

```yaml
entities:
  user:
    type: auth
    roles: role          # points to the field named "role"
    fields:
      role:
        type: enum
        values: [admin, moderator, user]
        default: user
```

The enum values in `fields.role.values` and the keys in `roles.user` must be consistent.

## When `roles:` is optional

If you have no role hierarchy (flat roles with no inclusion), you do not need a `roles:` section. Access rules with specific role names still work — they just don't inherit from any other role.

```yaml
# No roles: section needed
entities:
  user:
    type: auth
    roles: plan
    fields:
      plan:
        type: enum
        values: [free, pro, enterprise]
        default: free
```

With no hierarchy declared, `access: enterprise` matches only `enterprise`, not `pro` or `free`.

## Multiple auth entities

Each auth entity gets its own role hierarchy block:

```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
  apiClient:
    enterprise: [premium]
    premium: [free]
```

Role names are scoped to their entity. `user:admin` and `apiClient:enterprise` are independent.
