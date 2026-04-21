---
title: "Reference: Claim Mapping and Auto-Provision"
description: Controls how external provider (OIDC, SAML) identity data maps to entity fields and whether new records are created automatically on first login.
---

Controls how external provider (OIDC, SAML) identity data maps to entity fields and whether new records are created automatically on first login.

## Syntax

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      avatarUrl: { type: string }

# Auth block with external provider and claim mapping:
auth:
  identifier: email
  via: [password, google]
  claim_mapping:
    displayName: name       # entity field: provider claim
    avatarUrl: picture
  auto_provision: true
```

## Behavior

- **Parse time:** `claim_mapping` keys are validated as entity field names. `auto_provision` defaults to `false`.
- **Runtime (login):** The provider returns claims. The engine maps claims to entity fields using `claim_mapping`. If `auto_provision: true` and no matching record exists, a new one is created.

## Options

### `claim_mapping`

Maps entity field names (left) to provider claim names (right).

```yaml
claim_mapping:
  displayName: name       # entity field "displayName" <- provider claim "name"
  avatarUrl: picture      # entity field "avatarUrl" <- provider claim "picture"
```

Fields with identical names in both the entity and the provider are mapped automatically without needing `claim_mapping`.

For OIDC, standard claims include: `email`, `name`, `picture`, `sub`, `given_name`, `family_name`.

For SAML, claim names are the attribute names from the IdP assertion.

### `auto_provision`

| Value | Behavior |
|-------|----------|
| `true` | If no matching record exists (by `identifier`), create one using mapped claims + default role. |
| `false` (default) | If no matching record exists, return 401. The user must already exist. |

## Examples

### Google login with auto-provision

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [admin, user]
      default: user
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      avatarUrl: { type: string }

providers:
  google:
    type: oidc
    client_id: ${GOOGLE_CLIENT_ID}
    client_secret: ${GOOGLE_CLIENT_SECRET}
```

With the entity's `auth` block and a Google provider binding:

```yaml
auth:
  identifier: email
  via: [password, google]
  claim_mapping:
    displayName: name
    avatarUrl: picture
  auto_provision: true
```

On first Google login:
1. Engine receives `email` and `name` claims from Google.
2. No user record exists with that `email`.
3. `auto_provision: true` triggers record creation: `email` from claim, `displayName` from `name` claim, role defaults to the `roles.default` value.
4. JWT is issued. Subsequent logins match the existing record.

### Invite-only (no auto-provision)

```yaml
auth:
  identifier: email
  via: google
  claim_mapping:
    displayName: name
  auto_provision: false
```

The user must already exist (created manually or via another flow). If no record matches the `identifier`, login returns 401.

## Edge Cases

- **Missing claim from provider.** If a mapped claim is missing from the provider response, the corresponding entity field is set to `null` (not omitted).

- **Mapping to non-existent entity field.** If `claim_mapping` maps to a field name that does not exist in `fields:`, no parse-time error is raised. The mapped value is stored, but it is not in the Pydantic model, so it gets stripped from API responses.

- **`identifier` field must be mappable.** The `identifier` field must either be in `claim_mapping` or match a claim name exactly. Otherwise the system cannot match the user to a provider identity.

- **`auto_provision: true` with existing user.** If a user already exists (matched by `identifier`) and logs in via an external provider, the existing record is used. Claims are NOT used to update existing fields. Only new records are provisioned with claim data.

- **`auto_provision: true` with unique constraint failure.** If auto-provision tries to create a user but the unique constraint on the identifier fails (user already exists due to a race), the system treats it as a login instead.

- **`auto_provision: false` with no matching user.** Returns 401 Unauthorized.

## Errors

| Condition | HTTP Status | Response |
|-----------|-------------|----------|
| No matching user and `auto_provision: false` | 401 | Unauthorized |
| Provider returns invalid/missing claims | depends on claim | Field set to `null` |

## See Also

- [Auth overview](./overview.md)
- [Password provider](./password-provider.md)
- [Roles overview](../roles/overview.md)
