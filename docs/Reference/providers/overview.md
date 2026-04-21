# Reference: Providers Overview

The top-level `providers:` section declares external identity providers (OIDC, SAML) that can be referenced in entity `via:` bindings.

## Structure

```yaml
providers:
  google:
    type: oidc
    client_id: ${GOOGLE_CLIENT_ID}
    client_secret: ${GOOGLE_CLIENT_SECRET}
  okta:
    type: saml
    idp_metadata_url: ${OKTA_METADATA_URL}
    sp_entity_id: ${APP_URL}
```

Each key under `providers:` is a provider name. The name is referenced in the `auth.via` field on auth entities:

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: google      # references providers.google
```

## Provider types

| Type | Description |
|------|-------------|
| `oidc` | OpenID Connect. Uses discovery URL to get endpoints. |
| `saml` | SAML 2.0 service provider. |

## Well-known providers

These provider names have built-in discovery URLs and do not require a `discovery_url:` field:

| Name | Discovery URL |
|------|---------------|
| `google` | `https://accounts.google.com/.well-known/openid-configuration` |
| `microsoft` | `https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration` |
| `apple` | `https://appleid.apple.com/.well-known/openid-configuration` |

## Built-in providers (no declaration needed)

These do not need to appear in `providers:`:

- `password` — built-in, always available
- `apiKey` — built-in, always available

Only external (OIDC/SAML) providers need to be declared in `providers:`.
