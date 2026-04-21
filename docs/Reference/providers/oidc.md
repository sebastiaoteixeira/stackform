# Reference: OIDC Provider

OpenID Connect provider configuration for external SSO login.

## Schema

```yaml
providers:
  providerName:
    type: oidc
    client_id: ${CLIENT_ID}
    client_secret: ${CLIENT_SECRET}
    discovery_url: https://auth.example.com/.well-known/openid-configuration  # optional for well-known
```

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | Must be `oidc`. |
| `client_id` | yes | OAuth2 client ID from the provider's developer console. |
| `client_secret` | yes | OAuth2 client secret. Always use `${VAR}` interpolation. |
| `discovery_url` | no | OIDC discovery endpoint. Inferred automatically for well-known providers. |

## Well-known providers

These provider names infer `discovery_url` automatically:

```yaml
providers:
  google:
    type: oidc
    client_id: ${GOOGLE_CLIENT_ID}
    client_secret: ${GOOGLE_CLIENT_SECRET}
    # discovery_url is inferred

  microsoft:
    type: oidc
    client_id: ${MS_CLIENT_ID}
    client_secret: ${MS_CLIENT_SECRET}

  apple:
    type: oidc
    client_id: ${APPLE_CLIENT_ID}
    client_secret: ${APPLE_CLIENT_SECRET}
```

## Custom OIDC provider

For any other OIDC-compliant provider, supply `discovery_url:` explicitly:

```yaml
providers:
  okta:
    type: oidc
    client_id: ${OKTA_CLIENT_ID}
    client_secret: ${OKTA_CLIENT_SECRET}
    discovery_url: https://${OKTA_DOMAIN}/.well-known/openid-configuration

  auth0:
    type: oidc
    client_id: ${AUTH0_CLIENT_ID}
    client_secret: ${AUTH0_CLIENT_SECRET}
    discovery_url: https://${AUTH0_DOMAIN}/.well-known/openid-configuration
```

## Generated routes

For each entity with an OIDC provider binding, the engine generates:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/{base_path}/auth/{providerName}` | Redirect to provider's authorization endpoint |
| GET | `/{base_path}/auth/{providerName}/callback` | Handle OAuth2 callback, issue JWT |

Example with `base_path: /users` and provider `google`:

```
GET /users/auth/google             → redirect to Google
GET /users/auth/google/callback    → handle Google callback
```

## Entity binding

```yaml
entities:
  user:
    type: auth
    via:
      - provider: google
        identifier: email
        claim_mapping:
          displayName: name
        auto_provision: true
```

See [claim-mapping](./../../auth/claim-mapping.md) for `claim_mapping` and `auto_provision` details.
