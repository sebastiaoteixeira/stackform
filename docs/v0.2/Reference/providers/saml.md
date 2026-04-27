---
title: "Reference: SAML Provider"
description: SAML 2.0 Service Provider configuration for enterprise SSO.
---

SAML 2.0 Service Provider configuration for enterprise SSO.

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
| `idp_metadata_url` | yes | URL to the Identity Provider's SAML metadata XML. |
| `sp_entity_id` | yes | Service Provider entity ID (typically your app's base URL). |

## Example

```yaml
providers:
  okta:
    type: saml
    idp_metadata_url: ${OKTA_METADATA_URL}
    sp_entity_id: ${APP_URL}

  adfs:
    type: saml
    idp_metadata_url: ${ADFS_METADATA_URL}
    sp_entity_id: ${APP_URL}
```

## Entity binding

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: okta
```

SAML claim names are typically URNs or URLs. Use `claim_mapping` to map them to entity fields. See [claim-mapping](../../auth/claim-mapping.md).

## Generated routes

For each entity with a SAML provider binding, the engine generates:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{base_path}/auth/{providerName}` | Initiate SAML authentication (redirect to IdP) |
| POST | `/{base_path}/auth/{providerName}/acs` | Assertion Consumer Service endpoint (IdP posts here) |
| GET | `/{base_path}/auth/{providerName}/metadata` | SP metadata XML (register this with your IdP) |

Example with `base_path: /users` and provider `okta`:

```
GET  /users/auth/okta             → redirect to Okta
POST /users/auth/okta/acs         → receive SAML assertion
GET  /users/auth/okta/metadata    → SP metadata XML
```

Register the ACS URL and SP entity ID with your Identity Provider using the metadata endpoint.
