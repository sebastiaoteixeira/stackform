---
title: "OIDC Provider"
description: OpenID Connect single sign-on provider configuration, the generated login/callback flow, and the Keycloak audience setup for IdP-trusted tokens.
---

OpenID Connect provider configuration for external SSO login. A provider is
declared once under the top-level `providers:` block, then named by an auth
entity in `auth.via` (see [Entity binding](#entity-binding) below).

## Schema

```yaml
providers:
  myoidc:
    type: oidc
    client_id: my-app
    client_secret: ${OIDC_CLIENT_SECRET}
    discovery_url: ${OIDC_DISCOVERY_URL:-https://idp.example.com/.well-known/openid-configuration}
```

The provider object is closed: only the fields below are accepted, and any other
key fails with `SCHEMA_VALIDATION_ERROR`. Any value supports `${VAR}`
interpolation, including the `${VAR:-default}` form, resolved at build time. The
generated backend reads `client_secret` at run time from a
`<PROVIDER>_CLIENT_SECRET` env var (e.g. `KEYCLOAK_CLIENT_SECRET`) backed by a
pydantic `SecretStr` setting and seeded with the spec value; keep the literal
secret out of the spec file -- see
[Environment variables](../configuration/environment-variables.md).

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | Must be `oidc`. |
| `trust` | no | `app` (default) or `idp`. See [Token trust](./overview.md#token-trust). |
| `client_id` | yes | OAuth2 client ID from the provider's developer console. |
| `discovery_url` | yes | OIDC discovery endpoint (`.../.well-known/openid-configuration`). The generated routes read `authorization_endpoint`, `token_endpoint`, `userinfo_endpoint` and `jwks_uri` from it. There is no automatic inference for "well-known" provider names. |
| `client_secret` | no, `trust: app` only | OAuth2 client secret. Omit it for a public client; the token exchange then runs without a `client_secret`. |
| `issuer` | no, `trust: idp` only | Override for the expected token `iss`; read from the discovery document by default. |
| `audiences` | no, `trust: idp` only | The accepted token `aud` values. Defaults to `[client_id]`, and generation then warns with `TRUST_IDP_AUDIENCE_DEFAULTED`. |

`client_secret` under `trust: idp`, and `issuer` or `audiences` under
`trust: app`, fail with `SCHEMA_VALIDATION_ERROR`.

## Custom OIDC provider

Any standards-compliant OIDC identity provider works the same way -- supply its
`discovery_url` and the client issued for your app. You can declare several
providers side by side:

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

A provider is inert until an auth entity names it in `auth.via`. A binding object
carries the provider's own identifier, claim mapping and provisioning rule, and may
sit beside the built-in `password` provider:

```yaml
api:
  basePath: /api
  version: v1

entities:
  user:
    type: auth
    auth:
      identifier: email
      via:
        - provider: password
        - provider: myoidc
          identifier: email
          claim_mapping:
            email: email
            name: name
            firstName: given_name
            lastName: family_name
          auto_provision: true
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      name: { type: string }
      firstName: { type: string }
      lastName: { type: string }
```

| Binding field | Required | Description |
|---------------|----------|-------------|
| `provider` | yes | `password`, `apiKey`, or the name of a provider declared under `providers:`. |
| `identifier` | no | Local field used to find or create the user. Defaults to the entity's `auth.identifier`. |
| `claim_mapping` | no | Maps local field names to OIDC claim names (`localField: oidcClaim`). |
| `auto_provision` | no | Create the user on first login when no match is found. Defaults to `true`. |
| `relations` | no | Fills a foreign key with the id of a record whose fields match claims; see [Claim mapping](../auth/claim-mapping.md). |

If `claim_mapping` does not supply the identifier, the callback falls back to
the `email`, `login`, or `sub` claim, in that order. A binding naming an
undeclared provider fails with `BINDING_PROVIDER_NOT_FOUND`, and an `identifier`
that is not a field of the entity fails with `BINDING_IDENTIFIER_FIELD_NOT_FOUND`.

## Generated routes

Routes are emitted only for identity collections that sign users in through an
OIDC provider. Paths are prefixed with the API base path and version from your
`api:` block (`{basePath}[/{version}]`). With the binding above, the identity
collection `users` produces:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/users/auth/providers` | List the external providers of this collection (`[{name, type}]`). |
| GET | `/api/v1/users/auth/myoidc` | Redirect to the provider's `authorization_endpoint`. |
| GET | `/api/v1/users/auth/myoidc/callback?code=...` | Handle the OAuth2 callback and issue a one-time login code. |
| GET | `/api/v1/users/auth/myoidc/logout` | Redirect to the provider's `end_session_endpoint`. |
| POST | `/api/v1/auth/exchange` | Redeem a one-time login code for the app JWT. |

The provider name in the path is the key from `providers:` (here `myoidc`),
and the collection segment is the repository name. The `/auth/exchange`
endpoint is collection-independent and emitted once.

## Login and callback flow

1. The browser hits `GET /api/v1/users/auth/myoidc`. The server reads the
   discovery document and 302-redirects to the provider's
   `authorization_endpoint` with `response_type=code`,
   `scope=openid email profile` and a `state` value. The `redirect_uri` is this
   app's own `.../auth/myoidc/callback` URL.
2. The provider authenticates the user and redirects back to the callback with
   `code` and `state` query parameters.
3. The callback checks `state`, exchanges the code at the `token_endpoint`, then
   fetches the profile from the `userinfo_endpoint` (or `api.github.com/user`
   for `github`).
4. Claims are converted to the types of the fields they fill and mapped through
   `claim_mapping`; the user is matched on `identifier`. An existing user has
   the mapped fields brought up to date; a new one is created when
   `auto_provision` is `true`.
5. The server mints a single-use, short-lived login code and redirects to
   `{FRONTEND_URL}/auth/callback?code=<code>`. The app JWT never travels in a
   redirect URL. When `FRONTEND_URL` is unset, the redirect goes to this app's
   own base URL.
6. The single-page frontend reads the `code` query parameter and `POST`s it to
   `/api/v1/auth/exchange` as `{"code": "<code>"}`. The server redeems the code
   and returns `{"token": "<jwt>"}`. The code lives for 60 seconds and is
   redeemed atomically, so it works exactly once even across workers.

Set the `FRONTEND_URL` environment variable on the backend so the final redirect
lands on your UI rather than the API host.

## Errors during login

| Status | Condition |
|--------|-----------|
| 400 `Invalid OIDC state` | The callback's `state` does not match the login that started it. |
| 401 `Token exchange failed` | The `token_endpoint` rejected the authorization code. |
| 401 `Failed to fetch user info` | The `userinfo` (or GitHub user) request failed. |
| 401 `Token expired` | The provider returned an already-expired `exp` claim. |
| 401 `The provider's claims carry no usable '<identifier>'` | No claim yields a value the identifier field can hold. |
| 401 | Signing in would give the record a unique value another record already holds. |
| 403 `User not found and auto-provisioning is disabled` | No matching user and `auto_provision: false`. |
| 400 `Missing code` | `/auth/exchange` was called without a `code`. |
| 401 `Invalid or expired code` | The login code is unknown, already redeemed, or past its 60-second lifetime. |

## Keycloak: putting the API in `aud`

Under `trust: idp` the app verifies the access token's `aud` against `audiences`
(or `client_id`). A Keycloak access token names an audience only through protocol
mappers, so by default it does not carry the API and every request answers
`401 Invalid IdP token`. Add an **Audience** mapper so every access token the
clients receive names the API:

1. In the realm, open **Client scopes** and create a scope, for example
   `api-audience`.
2. In its **Mappers** tab choose **Configure a new mapper**, then **Audience**.
3. Set **Included Client Audience** to the API's client (the provider's
   `client_id`), or **Included Custom Audience** to a value listed in
   `audiences`, and turn **Add to access token** on.
4. In each client that calls the API, open **Client scopes** and add
   `api-audience` as a **Default** scope.

Every access token those clients obtain then carries the API in `aud`:

```yaml
providers:
  keycloak:
    type: oidc
    trust: idp
    client_id: orders-api
    discovery_url: https://sso.example.com/realms/main/.well-known/openid-configuration
    audiences: [orders-api]
```

Linking the scope as **Optional** instead adds the audience only when the client
requests `scope=api-audience`.

For the full credential and token lifecycle (password login plus SSO), see
[login-and-sso](../auth/login-and-sso.md). For claim mapping and
auto-provisioning detail, see [claim-mapping](../auth/claim-mapping.md).
