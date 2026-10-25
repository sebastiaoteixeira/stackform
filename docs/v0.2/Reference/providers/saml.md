---
title: "SAML Provider"
description: SAML 2.0 Service Provider configuration for enterprise SSO.
---

SAML 2.0 Service Provider configuration for enterprise SSO. A SAML provider is
declared once under `providers:` and becomes active only when an identity entity
names it in `auth.via`.

## Schema

```yaml
providers:
  providerName:
    type: saml
    idp_metadata_url: ${IDP_METADATA_URL}
    sp_entity_id: ${APP_URL}
```

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | Must be `saml`. |
| `idp_metadata_url` | yes | URL to the Identity Provider's SAML metadata XML. Fetched at request time on every login, callback, and metadata call. |
| `sp_entity_id` | yes | Service Provider entity ID (typically your app's base URL). |

Both `idp_metadata_url` and `sp_entity_id` support `${VAR}` interpolation, so keep
the IdP URL and entity ID in environment variables rather than hardcoding them.

## Example

```yaml
providers:
  mysaml:
    type: saml
    idp_metadata_url: ${IDP_METADATA_URL}
    sp_entity_id: ${APP_URL}

  my-other-saml:
    type: saml
    idp_metadata_url: ${OTHER_IDP_METADATA_URL}
    sp_entity_id: ${APP_URL}
```

## Binding it to an entity

A provider does nothing until an identity entity names it in `auth.via`. Put
`identifier`, `claim_mapping`, `auto_provision` and `relations` inside the binding
object.

```yaml
api:
  basePath: /api
  version: v1

providers:
  mysaml:
    type: saml
    idp_metadata_url: ${IDP_METADATA_URL}
    sp_entity_id: ${APP_URL}

entities:
  user:
    type: auth
    auth:
      identifier: email
      via:
        - provider: mysaml
          identifier: email
          claim_mapping:
            email: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
            name: "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
          auto_provision: true
    fields:
      id: { type: id }
      email: { type: string, required: true }
      name: { type: string }

repositories:
  users: { entity: user }
```

SAML claim names are typically URNs or URLs. Use `claim_mapping` to map them to
entity fields; only the keys you list are copied. See
[claim-mapping](../auth/claim-mapping.md) for the binding fields in detail.

## Generated routes

For each identity collection that signs users in through a SAML provider, the
`stackform run` development server and the generated FastAPI backend serve four
routes under the API prefix (`api.basePath` plus the optional `api.version`).
With the spec above:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/users/auth/mysaml` | Initiate SAML authentication (redirect to the IdP). |
| POST | `/api/v1/users/auth/mysaml/callback` | Assertion Consumer Service (ACS); the IdP posts the `SAMLResponse` form field here. |
| GET | `/api/v1/users/auth/mysaml/metadata` | SP metadata XML; register this with your IdP. |
| GET | `/api/v1/users/auth/mysaml/logout` | Redirect to the IdP's single logout service. |

The path segment after the prefix is `{collection}/auth/{provider}`, where
`{collection}` is the identity repository name and `{provider}` is the provider
key under `providers:`. Register the ACS URL (the `/callback` route) and the SP
entity ID with your Identity Provider; the metadata endpoint emits a ready
descriptor you can hand to the IdP. The `drf` and `raw` targets and
`stackform run --raw` reject a SAML provider with `BACKEND_FEATURE_UNSUPPORTED`.

## Callback

The ACS endpoint accepts only a response to a login this app started, and each
assertion only once. It maps the SAML attributes through `claim_mapping`, falls
back to the assertion `NameID` for the `identifier` field when no claim supplied
it, finds or provisions the user, and 303-redirects the browser to
`{FRONTEND_URL}/auth/callback?code=<code>`. The frontend redeems the one-time
code at `POST {prefix}/auth/exchange` for the app JWT, exactly as after an
[OIDC login](./oidc.md#login-and-callback-flow).

## Auto-provisioning

`auto_provision` defaults to `true`. When an authenticated SAML user has no matching
record, the backend creates one and signs them in. Set `auto_provision: false` to
require pre-existing accounts; an unknown user then gets:

```
403 {"detail": "User not found and auto-provisioning is disabled"}
```

## Error responses

| Status | When |
|--------|------|
| 400 | `Missing SAMLResponse` or `Malformed SAMLResponse`. |
| 401 | `SAML authentication failed: <reason>` when the assertion fails validation. |
| 401 | `SAML response answers no pending login` or `SAML assertion already consumed`. |
| 401 | The claims carry no usable identifier, or signing in would duplicate a unique value. |
| 403 | `User not found and auto-provisioning is disabled`. |

See also [Login, SSO, and the token flow](../auth/login-and-sso.md) for how the
React login page lists providers and how the token flow ties into the rest of auth.
