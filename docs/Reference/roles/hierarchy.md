# Reference: Role Hierarchy

Role hierarchy defines which roles subsume other roles. When a route requires role X, any principal with a role that includes X (directly or transitively) is also allowed.

## Definition

```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
```

`admin: [moderator]` means "admin includes moderator". A principal with role `admin` satisfies any check that requires `moderator`.

## Transitivity

Inclusion is transitive. Given:

```yaml
admin: [moderator]
moderator: [user]
```

- `admin` includes `moderator`, which includes `user`
- Therefore `admin` also includes `user`
- A principal with `admin` satisfies `access: user`, `access: moderator`, and `access: admin`

## Access rule matching

| Principal role | `access: user` | `access: moderator` | `access: admin` |
|---------------|---------------|--------------------|----|
| `user` | pass | fail | fail |
| `moderator` | pass | pass | fail |
| `admin` | pass | pass | pass |

## Example: tiered API access

```yaml
roles:
  apiClient:
    enterprise: [premium]
    premium: [free]
```

| Client tier | `access: apiClient:free` | `access: apiClient:premium` | `access: apiClient:enterprise` |
|------------|--------------------------|-----------------------------|-|
| `free` | pass | fail | fail |
| `premium` | pass | pass | fail |
| `enterprise` | pass | pass | pass |

## Cycles

Role hierarchies must be acyclic. A cycle (e.g., `admin: [user]`, `user: [admin]`) is a validation error.

## No cross-entity inheritance

Role hierarchy is strictly per-entity. `user:admin` and `apiClient:admin` are completely independent — there is no way to declare that one entity's role includes another entity's role.
