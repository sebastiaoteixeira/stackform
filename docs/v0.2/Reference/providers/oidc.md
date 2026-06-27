---
title: "OIDC Provider"
description: OpenID Connect single sign-on provider configuration and the generated login/callback flow.
---

OpenID Connect provider configuration for external SSO login. A provider is
declared once under the top-level `providers:` block, then attached to an auth
entity through `auth.bindings` (see [Entity binding](#entity-binding) below).

## Schema

```yaml
providers:
  myoidc:
    type: oidc
    client_id: my-app
    client_secret: ${OIDC_CLIENT_SECRET}
    discovery_url: ${OIDC_DISCOVERY_URL:-https://idp.example.com/.well-known/openid-configuration}
```

The provider object is closed (`additionalProperties: false`): only the four
fields below are accepted. Any value supports `${VAR}` interpolation, including
the `${VAR:-default}` form, so secrets and URLs stay out of the spec.

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | Must be `oidc`. |
| `client_id` | yes | OAuth2 client ID from the provider's developer console. |
| `client_secret` | yes | OAuth2 client secret. Always use `${VAR}` interpolation. |
| `discovery_url` | yes (effectively) | OIDC discovery endpoint (`.../.well-known/openid-configuration`). The JSON schema marks it optional, but the generated routes read `authorization_endpoint`, `token_endpoint`, and `userinfo_endpoint` from it, so login fails without it. There is no automatic inference for "well-known" provider names -- always supply it. |

## Custom OIDC provider

Any standards-compliant OIDC identity provider works the same way -- supply its
`discovery_url` and the credentials
issued for your client. You can declare several providers side by side:

```yaml
providers:
  myoidc:
    type: oidc
    client_id: ${OIDC_CLIENT_ID}
    client_secret: ${OIDC_CLIENT_SECRET}
    discovery_url: ${OIDC_DISCOVERY_URL}

  myotheroidc:
    type: oidc
    client_id: ${OTHER_OIDC_CLIENT_ID}
    client_secret: ${OTHER_OIDC_CLIENT_SECRET}
    discovery_url: ${OTHER_OIDC_DISCOVERY_URL}
```

### GitHub special case

GitHub does not implement OIDC. When the provider name is `github`, the
generated callback skips the discovery `userinfo_endpoint` and fetches the
profile from `https://api.github.com/user` instead. You still declare it as
`type: oidc` with a `discovery_url` (used only for the authorization and token
endpoints).

## Entity binding

A provider is inert until an auth entity binds to it. Attach it through
`auth.bindings` (not `auth.via`, which is reserved for the built-in `password`
and `apiKey` providers):

```yaml
api:
  basePath: /api
  version: v1

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
            email: email
            name: name
            firstName: given_name
            lastName: family_name
          auto_provision: true
```

| Binding field | Required | Description |
|---------------|----------|-------------|
| `provider` | yes | Name of a provider declared under `providers:`. |
| `identifier` | no | Local field used to find/create the user. Defaults to the entity's `auth.identifier`. |
| `claim_mapping` | no | Maps local field names to OIDC claim names (`localField: oidcClaim`). |
| `auto_provision` | no | Create the user on first login when no match is found. Defaults to `true`. |

If `claim_mapping` does not supply the identifier, the callback falls back to
the `email`, `login`, or `sub` claim, in that order.

## Generated routes

Routes are emitted only for identity collections that actually bind an OIDC
provider. Paths are prefixed with the API base path and version from your `api:`
block (`{basePath}[/{version}]`). With the binding above and
`api: { basePath: /api, version: v1 }`, the identity collection `users`
produces:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/users/auth/providers` | List the external providers bound to this collection (`[{name, type}]`). |
| GET | `/api/v1/users/auth/myoidc` | Redirect to the provider's `authorization_endpoint`. |
| GET | `/api/v1/users/auth/myoidc/callback?code=...` | Handle the OAuth2 callback and issue a one-time login code. |
| POST | `/api/v1/auth/exchange` | Redeem a one-time login code for the app JWT. |

The provider name in the path is the key from `providers:` (here `myoidc`),
and the collection segment is the repository/identity-collection name. The
`/auth/exchange` endpoint is collection-independent and emitted once whenever
any collection binds an OIDC provider.

## Login and callback flow

1. The browser hits `GET /api/v1/users/auth/myoidc`. The server reads the
   discovery document and 302-redirects to the provider's
   `authorization_endpoint` with `response_type=code` and
   `scope=openid email profile`. The `redirect_uri` is this app's own
   `.../auth/myoidc/callback` URL.
2. The provider authenticates the user and redirects back to the callback with
   a `code` query parameter.
3. The callback exchanges the code at the `token_endpoint`, then fetches the
   profile from the `userinfo_endpoint` (or `api.github.com/user` for `github`).
4. Claims are mapped to local fields via `claim_mapping`; the user is matched on
   `identifier`. An existing user is logged in; a new one is created when
   `auto_provision` is `true`.
5. The server mints a single-use, short-lived login code and 302-redirects to
   `{FRONTEND_URL}/auth/callback?code=<code>`. The app JWT never travels in a
   redirect URL. When `FRONTEND_URL` is unset, the redirect falls back to this
   app's own base URL.
6. The single-page frontend reads the `code` query parameter and `POST`s it to
   `/api/v1/auth/exchange` as `{"code": "<code>"}`. The server redeems the code
   and returns `{"token": "<jwt>"}`. The code is stored in an
   `_oidc_login_codes` collection in the identity collection's datastore, lives
   for 60 seconds, and is redeemed atomically (delete-on-read), so it works
   exactly once even across workers. A missing code returns 400 `Missing code`;
   an unknown or expired code returns 401 `Invalid or expired code`.

Set the `FRONTEND_URL` environment variable on the generated backend so the
final redirect lands on your UI rather than the API host.

## Errors during login

| Status | Condition |
|--------|-----------|
| 401 `Token exchange failed` | The `token_endpoint` rejected the authorization code. |
| 401 `Failed to fetch user info` | The `userinfo` (or GitHub user) request failed. |
| 401 `Token expired` | The provider returned an already-expired `exp` claim. |
| 403 `User not found and auto-provisioning is disabled` | No matching user and `auto_provision: false`. |
| 400 `Missing code` | `/auth/exchange` was called without a `code`. |
| 401 `Invalid or expired code` | The login code is unknown, already redeemed, or past its 60-second TTL. |

For the full credential and token lifecycle (password login plus SSO), see
[login-and-sso](../auth/login-and-sso.md). For claim mapping and
auto-provisioning detail, see [claim-mapping](../auth/claim-mapping.md).
