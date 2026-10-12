---
title: "Claim Mapping and Auto-Provision"
description: How an external provider's identity claims (OIDC, SAML) map to entity fields on a per-binding basis, and whether a new record is created automatically on first SSO login.
---

External providers are attached to an auth entity through `auth.bindings`. Each binding
names a configured `provider`, the local `identifier` field used to match an existing
record, an optional `claim_mapping` (provider claim -> entity field), and `auto_provision`
(create a record on first login). Claim mapping and auto-provision are properties of a
binding, not of `auth.via`. `via` is for the built-in `password` and `apiKey` providers.

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

## Syntax

```yaml
providers:
  myoidc:
    type: oidc
    client_id: ${OIDC_CLIENT_ID}
    client_secret: ${OIDC_CLIENT_SECRET}
    discovery_url: ${OIDC_DISCOVERY_URL:-https://idp.example.com/.well-known/openid-configuration}

entities:
  myEntity:
    type: auth
    auth:
      identifier: email
      via: password
      bindings:
        - provider: myoidc
          identifier: email
          claim_mapping:
            displayName: name      # entity field: provider claim
            avatarUrl: picture
          auto_provision: true
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true, format: email }
      displayName: { type: string, required: true }
      avatarUrl: { type: string }
```

OIDC providers require `discovery_url`; the callback flow reads
`authorization_endpoint`, `token_endpoint`, and `userinfo_endpoint` from that document.
There is no built-in inference of well-known endpoints for any provider name.

## Behavior

- **Parse time:** A binding requires `provider` and `identifier`. `claim_mapping` keys are
  taken verbatim; they are not validated against `fields:`. `auto_provision` defaults to
  `true`.
- **Runtime (SSO login):** The provider returns claims. For every `entity field: claim`
  pair in `claim_mapping`, if that claim is present in the provider response, the value is
  copied to the entity field. The binding's `identifier` value is used to look up an
  existing record. If none is found and `auto_provision: true`, a record is created from
  the mapped fields.

## Options

### `claim_mapping`

Maps entity field names (left) to provider claim names (right).

```yaml
claim_mapping:
  displayName: name       # entity field "displayName" from provider claim "name"
  avatarUrl: picture      # entity field "avatarUrl" from provider claim "picture"
```

Only the keys you list are copied. There is no automatic mapping of identically named
claims; an unmapped claim is ignored.

If the binding's `identifier` field is not produced by `claim_mapping`, the engine fills
it from a fallback so the user can still be matched:

- OIDC: the first present of `email`, `login`, then `sub`.
- SAML: the assertion `NameID`.

For OIDC, standard claims include `email`, `name`, `picture`, `sub`, `given_name`,
`family_name`. For SAML, claim names are the attribute names from the IdP assertion (each
attribute's first value is used).

### `auto_provision`

| Value | Behavior |
|-------|----------|
| `true` (default) | If no record matches the binding `identifier`, create one from the mapped claim values. The generated id is a `uuid4`. No role is assigned at provision time. |
| `false` | If no record matches, return 403 with detail `User not found and auto-provisioning is disabled`. The user must already exist. |

A provisioned record contains only the mapped claim fields plus the generated id. Any
field with a YAML `default:` is not auto-filled by the SSO path, and no role is set, so a
default role for SSO users must come from another flow.

## Examples

### OIDC login with auto-provision

```yaml
api:
  basePath: /api
  version: v1
  operations:
    auth:
      login: true

providers:
  myoidc:
    type: oidc
    client_id: ${OIDC_CLIENT_ID}
    client_secret: ${OIDC_CLIENT_SECRET}
    discovery_url: ${OIDC_DISCOVERY_URL:-https://idp.example.com/.well-known/openid-configuration}

entities:
  myEntity:
    type: auth
    auth:
      identifier: email
      via: password
      bindings:
        - provider: myoidc
          identifier: email
          claim_mapping:
            displayName: name
            avatarUrl: picture
          auto_provision: true
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true, format: email }
      displayName: { type: string, required: true }
      avatarUrl: { type: string }
```

On first SSO login (the browser visits `GET /api/v1/my-collection/auth/myoidc`):

1. The engine redirects to the provider, then the callback exchanges the `code` and fetches
   the userinfo claims.
2. `email`, `name`, and `picture` are read from the claims; `displayName` and `avatarUrl`
   are populated via `claim_mapping`, and `email` is the identifier.
3. No record matches that `email`, so `auto_provision: true` creates one with `email`,
   `displayName`, `avatarUrl`, and a generated `uuid4` id.
4. A single-use login code is minted and the browser is redirected to
   `{FRONTEND_URL}/auth/callback?code=<code>`; the SPA redeems it at
   `/auth/exchange` for the application JWT. Subsequent logins match the existing record.

### Invite-only (no auto-provision)

```yaml
auth:
  identifier: email
  via: password
  bindings:
    - provider: myoidc
      identifier: email
      claim_mapping:
        displayName: name
      auto_provision: false
```

The user must already exist (created via password registration or another flow). If no
record matches the binding `identifier`, the SSO callback returns 403 with detail
`User not found and auto-provisioning is disabled`.

## What a successful SSO login returns

The two SSO callbacks differ in shape:

- **OIDC** (`GET .../auth/{provider}/callback?code=...`): on success, the engine mints a
  single-use login code and issues a 302 redirect to `{FRONTEND_URL}/auth/callback?code=<code>`
  (when `FRONTEND_URL` is unset, the request base URL is used). The SPA then `POST`s the code
  to `/auth/exchange` and receives the application's own JWT, not the provider token.
- **SAML** (`POST .../auth/{provider}/callback`): on success, the engine returns JSON
  `{"token": "<jwt>", "user": {...}}` with `_id` and `_auth` stripped from the user object.

With `api: { basePath: /api, version: v1 }`, the OIDC routes are
`/api/v1/{collection}/auth/{provider}` and `/api/v1/{collection}/auth/{provider}/callback`,
plus `/api/v1/{collection}/auth/providers` listing the configured external providers.

### GitHub special case

GitHub does not implement OIDC userinfo. When the provider name is `github`, the callback
fetches the profile from `https://api.github.com/user` (using the access token) instead of
a discovery `userinfo_endpoint`; everything else (claim mapping, matching, provisioning) is
the same.

### Environment-variable interpolation

`client_id`, `client_secret`, and `discovery_url` accept `${VAR}` interpolation, so secrets
stay out of the spec. `client_id` and `discovery_url` are resolved at build time;
`client_secret` is read at run time from a `<PROVIDER>_CLIENT_SECRET` env var
(e.g. `KEYCLOAK_CLIENT_SECRET`) via a `SecretStr` setting, never baked as a literal:

```yaml
providers:
  myoidc:
    type: oidc
    client_id: my-app
    client_secret: ${OIDC_CLIENT_SECRET}
    discovery_url: ${OIDC_DISCOVERY_URL:-https://idp.example.com/.well-known/openid-configuration}
```

## Edge Cases

- **Missing claim from provider.** If a mapped claim is absent from the provider response,
  the corresponding entity field is simply omitted from the created record (not set to
  `null`).

- **Mapping to a non-existent entity field.** `claim_mapping` keys are not validated against
  `fields:` at parse time. The mapped value is written to the record verbatim, but a field
  not declared in the Pydantic model is stripped from CRUD API responses.

- **`identifier` not in `claim_mapping`.** The engine fills the identifier from the fallback
  (OIDC: `email`/`login`/`sub`; SAML: `NameID`). If none of those are present either, the
  lookup uses an empty value and likely fails to match.

- **Existing user.** If a record already matches the binding `identifier`, that record is
  used and a fresh application JWT is issued. Mapped claims are NOT written back to the
  existing record; only new records receive claim data.

## Errors

| Condition | HTTP Status | Response |
|-----------|-------------|----------|
| OIDC token exchange fails | 401 | `Token exchange failed` |
| OIDC userinfo fetch fails | 401 | `Failed to fetch user info` |
| Provider token already expired | 401 | `Token expired` |
| SAML assertion error / not authenticated | 401 | `SAML error: ...` / `SAML authentication failed` |
| No matching record and `auto_provision: false` | 403 | `User not found and auto-provisioning is disabled` |

## See Also

- [Auth overview](./overview.md)
- [Password provider](./password-provider.md)
- [Roles overview](../roles/overview.md)
