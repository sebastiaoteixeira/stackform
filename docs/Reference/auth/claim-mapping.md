# Reference: Claim Mapping and Auto-Provision

`claim_mapping` and `auto_provision` apply to external provider bindings (OIDC, SAML). They control how provider identity data is mapped to entity fields and whether new records are created automatically.

## `claim_mapping`

Maps entity field names to provider claim names.

```yaml
via:
  - provider: google
    identifier: email
    claim_mapping:
      displayName: name       # entity field: provider claim
      avatarUrl: picture
```

- The left side is the entity field name (declared in `fields:`).
- The right side is the claim name from the provider's token or assertion.

Fields with identical names in both the entity and the provider are mapped automatically without needing `claim_mapping`.

For OIDC, standard claims include: `email`, `name`, `picture`, `sub`, `given_name`, `family_name`.

For SAML, claim names are the attribute names from the IdP assertion.

## `auto_provision`

Type: boolean. Default: `false`.

When `true`, if a user authenticates via the external provider but no matching entity record exists (matched by the `identifier` field), a new record is created automatically using the mapped claims.

```yaml
via:
  - provider: google
    identifier: email
    claim_mapping:
      displayName: name
    auto_provision: true
```

When `false` (default), the user must already have an existing record with the matching `identifier` value to log in. Use this when you control user creation manually (e.g., invite-only apps).

## Example: Google login with auto-provision

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
          avatarUrl: picture
        auto_provision: true
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      avatarUrl: { type: string }
      role:
        type: enum
        values: [admin, user]
        default: user
```

On first Google login:
1. Engine receives `email` and `name` claims from Google.
2. No user record exists with that `email`.
3. `auto_provision: true` → creates a new user record: `email` from claim, `displayName` from `name` claim, `role` defaults to `user`.
4. JWT is issued. Subsequent logins match the existing record.

## Merging accounts

If a user already exists (matched by `identifier`) and logs in via an external provider, the existing record is used. Claims are not used to update existing fields. Only new records are provisioned with claim data.
