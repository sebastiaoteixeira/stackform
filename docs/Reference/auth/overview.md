# Reference: Auth Overview

An entity becomes an identity provider by setting `type: auth` and declaring `via:` bindings.

## Entity declaration

```yaml
entities:
  user:
    type: auth
    via:
      - provider: password
        identifier: email
      - provider: google
        identifier: email
        claim_mapping:
          displayName: name
        auto_provision: true
    roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user
```

## `type: auth`

Marks the entity as an identity provider. Only one value is valid: `"auth"`.

Effects:
- Generates `register` and `login` endpoints (controlled by `api.operations.auth`)
- Principals authenticated via this entity receive a JWT with `sub` set to the identifier field value
- The entity participates in ABAC rules as `identity:entityName`

## `via:`

A list of provider bindings. Each binding defines one authentication method for this entity.

```yaml
via:
  - provider: password       # built-in: password hash
    identifier: email        # field used as username
  - provider: apiKey         # built-in: API key in header
    identifier: clientId     # field used as client identifier
  - provider: google         # references top-level providers.google
    identifier: email
    claim_mapping:
      displayName: name
    auto_provision: true
```

### Binding fields

| Field | Required | Description |
|-------|----------|-------------|
| `provider` | yes | `password`, `apiKey`, or a key from top-level `providers:` |
| `identifier` | yes | Entity field used to identify the principal |
| `claim_mapping` | no | Map of entity fields to provider claims (external providers only) |
| `auto_provision` | no | Create entity record on first external login. Default: `false`. |

## `roles:`

Points to an enum field on this entity. Enables role-based access control.

```yaml
roles: role   # "role" is the field name
```

The field must be declared in `fields:` as `type: enum`. The enum values become the valid role names for this entity.

Without `roles:`, the entity still authenticates principals but has no role-based access control. `access: "*"` and `access: user:*` still work; `access: user:admin` requires `roles:` to be set.

## Internal storage

Auth-related fields (password hashes, API keys) are stored under a `_auth` namespace in MongoDB, not as flat top-level fields. The `principal.record` object returned by access rules contains only the entity's declared fields — internal fields are filtered out.

```
# MongoDB document (internal)
{ "id": "abc", "email": "alice@example.com", "_auth": { "passwordHash": "pbkdf2:..." } }

# principal.record (what access rules see)
{ "id": "abc", "email": "alice@example.com", "displayName": "Alice", "role": "user" }
```

## Multiple auth entities

A spec can have multiple auth entities. When multiple exist, all access rule role references must use the entity prefix:

```yaml
access: user:admin       # required when multiple auth entities exist
access: apiClient:enterprise
```

Unscoped `admin` is a validation error when multiple auth entities are present. See [access-control](../controllers/access-control.md).
