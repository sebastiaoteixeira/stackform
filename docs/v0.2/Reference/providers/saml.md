---
title: "SAML Provider"
description: SAML 2.0 Service Provider configuration for enterprise SSO.
---

SAML 2.0 Service Provider configuration for enterprise SSO. A SAML provider is
declared once under `providers:` and becomes active only when an identity entity
binds to it through `auth.bindings`.

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

A provider does nothing until an identity entity binds to it. Attach SAML through
`auth.bindings` (not `auth.via`, which is reserved for the built-in `password` and
`apiKey` providers). Put `identifier`, `claim_mapping`, and `auto_provision` inside
the binding.

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
      bindings:
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
```

SAML claim names are typically URNs or URLs. Use `claim_mapping` to map them to
entity fields; only the keys you list are copied. See
[claim-mapping](../auth/claim-mapping.md) for the binding fields in detail.

## Generated routes

For each entity that binds a SAML provider, the engine generates three routes. They
are mounted under the API prefix (`api.basePath` plus the optional `api.version`),
so with the `api:` block above (`basePath: /api`, `version: v1`) and an entity
collection `user` bound to provider `mysaml`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/user/auth/mysaml` | Initiate SAML authentication (redirect to IdP). |
| POST | `/api/v1/user/auth/mysaml/callback` | Assertion Consumer Service (ACS); the IdP posts the `SAMLResponse` form field here. |
| GET | `/api/v1/user/auth/mysaml/metadata` | SP metadata XML; register this with your IdP. |

The path segment after the prefix is `{collection}/auth/{provider}`, where
`{collection}` is the identity entity's collection name and `{provider}` is the
provider key under `providers:`. Register the ACS URL (the `/callback` route) and
the SP entity ID with your Identity Provider; the metadata endpoint emits a ready
descriptor you can hand to the IdP.

If you omit `api.version`, the prefix is just `basePath`, so the routes become
`/api/user/auth/mysaml`, `/api/user/auth/mysaml/callback`, and
`/api/user/auth/mysaml/metadata`.

## Callback response

On a successful assertion the ACS endpoint maps the SAML attributes through
`claim_mapping`, falls back to the assertion `NameID` for the `identifier` field
when no claim supplied it, finds or provisions the user, and returns the
application's own JWT plus the sanitized record as JSON:

```json
{
  "token": "<app-jwt>",
  "user": { "id": "...", "email": "user@example.com", "name": "..." }
}
```

The returned `user` has `_id` and `_auth` stripped. The `token` is your app's JWT,
not the IdP assertion; send it back as `Authorization: Bearer <token>` on
subsequent requests.

## Auto-provisioning

`auto_provision` defaults to `true`. When an authenticated SAML user has no matching
record, the backend creates one (assigning a new `uuid4` id) and logs them in. Set
`auto_provision: false` to require pre-existing accounts; an unknown user then gets:

```
403 {"detail": "User not found and auto-provisioning is disabled"}
```

## Error responses

| Status | When |
|--------|------|
| 401 | `{"detail": "SAML error: <messages>"}` when the assertion fails validation. |
| 401 | `{"detail": "SAML authentication failed"}` when the response is processed but not authenticated. |
| 403 | `{"detail": "User not found and auto-provisioning is disabled"}` when the user is unknown and `auto_provision` is off. |

See also [Login, SSO, and the token flow](../auth/login-and-sso.md) for how the
React login page lists providers and how the token flow ties into the rest of auth.
