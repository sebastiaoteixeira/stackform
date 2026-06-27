---
title: "Environment Variables and Interpolation"
description: Substitutes environment variable values into YAML string scalars after the YAML is parsed and before schema validation, plus the runtime variables the generated backend, the dev server, and a Docker deploy read directly.
---

There are two distinct ways environment variables reach a generated app, and they do
not overlap:

1. **Spec interpolation (build time).** `${VAR}` or `${VAR:-default}` inside any
   string value in the YAML spec is a build-time macro. It is resolved by the parser
   from the environment when the spec is loaded -- for both `yaml-api build` and
   `yaml-api run` -- and the resolved value is baked into the output. There is no
   runtime deferral: no spec field is special-cased as a "runtime secret", so a
   `${VAR}` reference never survives into the artifact as a placeholder.
2. **Runtime variables.** The generated backend, the `yaml-api run` dev server, and
   a generated Docker deploy read a fixed set of variables (listed under
   [Runtime variables](#runtime-variables)) directly from the process environment at
   run time. These are read by the generated *code*, not by spec interpolation, and
   are never written in the spec.

> **Secrets.** Because spec interpolation is build-time only, a secret written as
> `${SECRET}` in the spec is resolved at build time and baked into the built
> artifact. If a secret must stay out of the build, do not place it in the spec at
> all -- the deployed backend reads its own runtime environment directly (see the
> [Runtime variables](#runtime-variables) the generated code reads). This is a change
> from earlier versions, which deferred certain fields (such as `client_secret` or a
> datastore password) to runtime via a settings layer; no such deferral exists now.

## Spec Interpolation

### Required variable

```yaml
mongo:
  uri: ${MONGO_URI}
```

If `MONGO_URI` is not set in the environment, loading the spec aborts with exit code
1 and the error `INTERPOLATION_MISSING_VAR`.

### Variable with fallback

```yaml
mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-my-app}
```

If the variable is not set, the fallback value after `:-` is used.

### Options

| Syntax | Behavior |
|--------|----------|
| `${VAR}` | Replaced with the value of `VAR`. Error if `VAR` is not set. |
| `${VAR:-default}` | Replaced with the value of `VAR` if set; otherwise uses `default`. |

A variable name must start with a letter or underscore and contain only letters,
digits, and underscores: `[A-Za-z_][A-Za-z0-9_]*`. Anything that does not match the
`${...}` shape is left untouched.

## When Interpolation Runs

- The spec is first parsed with the YAML loader into a Python structure.
- Interpolation then walks that structure and rewrites each **string scalar** in
  place, resolving every `${...}` it contains.
- Schema validation and the rest of generation run on the interpolated result.

Because interpolation operates on already-parsed string scalars (not on the raw file
text), the substituted value stays a string. It is not re-parsed as YAML: `${VAR}`
expanding to `true` or `42` yields the strings `"true"` / `"42"`, not a boolean or
number. If you need a numeric or boolean field driven by the environment, the field
must accept a string or you must set the literal value in the spec.

Runtime variables are read separately by the generated code at run time and have
nothing to do with this parse-time step.

## Where Interpolation Applies

Interpolation works in any string value anywhere in the spec:

```yaml
mongo:
  uri: ${MONGO_URI}
  database: ${MONGO_DB:-myapp}

providers:
  myoidc:
    type: oidc
    client_id: ${OIDC_CLIENT_ID}
    client_secret: ${OIDC_CLIENT_SECRET}
    discovery_url: ${OIDC_DISCOVERY_URL:-https://idp.example.com/.well-known/openid-configuration}

api:
  basePath: ${API_BASE_PATH:-/api}
```

## What is NOT Interpolated

- YAML keys (left-hand side of `:`).
- Non-string values. Only string scalars are scanned, so booleans, numbers, `null`,
  and structures (lists/maps) pass through unchanged.

## Runtime Variables

These variables are read directly from the process environment by the running code,
not via spec interpolation. They are grouped by who reads them.

### Generated backend (`yaml-api build`, fastapi/raw targets)

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string. |
| `MONGO_DB` | `yaml_api` | MongoDB database name. |
| `JWT_SECRET` | *(required)* | HMAC key for JWT signing (HS256). The field has no default, so the generated backend fails fast at startup if it is unset. |
| `JWT_EXPIRATION_HOURS` | `24` | JWT token lifetime in hours. |
| `PASSWORD_HASH_ROUNDS` | `390000` | PBKDF2-HMAC-SHA256 iteration count for password hashing. |
| `FRONTEND_URL` | `""` | Base URL the OIDC callback redirects to (`{FRONTEND_URL}/auth/callback?code=...`). Falls back to the request base URL when unset. |
| `HOST` | `127.0.0.1` | Host the generated `app.py` binds to when run directly. |
| `PORT` | `api.port` (or `8000`) | Port the generated `app.py` binds to when run directly. |

The compile-time `mongo.uri` / `mongo.database` from the spec are only baked into the
Docker deploy defaults; the generated backend itself always reads `MONGO_URI` /
`MONGO_DB` at run time, falling back to the values above.

**Warning:** `JWT_SECRET` is required. Set it to a strong random value (for example
`openssl rand -hex 32`) in every environment, including local runs of the generated
backend. A generated Docker deploy auto-fills a dev-ready value for you (see [Docker
deploy](#docker-deploy-yaml-api-build--deploy)).

### `yaml-api run` dev server

| Variable | Default | Description |
|----------|---------|-------------|
| `YAML_API_MONGO_URI` | `mongo.uri` from the spec | MongoDB connection string for the dev server. |
| `YAML_API_MONGO_DB` | `mongo.database` from the spec | MongoDB database name for the dev server. |

The dev server reads `JWT_SECRET`, `JWT_EXPIRATION_HOURS`, `PASSWORD_HASH_ROUNDS`,
and `FRONTEND_URL` the same way the generated backend does, with one difference:
`JWT_SECRET` falls back to the insecure default `yaml-api-dev-secret-change-me` when
unset, so the dev server starts without configuration. The generated backend has no
such fallback and requires `JWT_SECRET`. Note that `run` uses `YAML_API_MONGO_URI` /
`YAML_API_MONGO_DB` (NOT `MONGO_URI` / `MONGO_DB`), and that its bind host and port
come from the `--host` / `-p` flags, not from `HOST` / `PORT`.

```bash
YAML_API_MONGO_URI=mongodb://localhost:27017 \
YAML_API_MONGO_DB=myapp \
JWT_SECRET=$(openssl rand -hex 32) \
yaml-api run myapp.yaml --host 0.0.0.0 -p 8000
```

### Docker deploy (`yaml-api build ... deploy`)

The generated `docker-compose.yml` exposes these for `docker compose`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://mongodb:27017` | Backend MongoDB connection string inside the compose network. |
| `MONGO_DB` | `mongo.database` from the spec | Backend MongoDB database name. |
| `APP_PORT` | `deploy.port` | Host port mapped to the backend container. |
| `FRONTEND_PORT` | `80` | Host port mapped to the frontend container. |
| `VITE_API_BASE_URL` | `http://localhost:<port>/api/v1` | API base URL baked into the built frontend. |
| `BACKEND_URL` | `http://app:<port>` | Upstream the frontend's nginx proxies to (set by the container entrypoint). |

#### Secrets in the generated deploy

The deploy emits each backend secret as `${NAME:-<default>}` in `docker-compose.yml`
and lists it in the generated `.env`. These secrets are the framework runtime
variables the generated code reads (currently only `JWT_SECRET`), not values pulled
from spec interpolation -- a `${VAR}` in the spec has already been resolved and baked
in by the time the deploy is generated.

`JWT_SECRET` is generated: it gets a unique dev-ready value produced at generation
time with `secrets.token_urlsafe(32)`, so the deploy runs out of the box. Override it
for production by setting the variable in the environment or `.env`.

Any additional runtime variables your backend needs (for example a secret the backend
reads directly rather than one interpolated into the spec) are declared explicitly in
the spec's `deploy.env_vars` list; those are emitted with an empty default for you to
fill.

## Generated `.env` / `.env.example`

When a `deploy:` block is present, `yaml-api build ... deploy` writes a `.env`
listing the runtime variables the generated backend reads: the framework secret
variables (currently `JWT_SECRET`, pre-filled with a generated dev value) plus
whatever is declared in the spec's `deploy.env_vars`. It does **not** scan the spec
for `${VAR}` interpolation references -- those are build-time macros, already resolved
and baked into the artifact before the deploy is generated, so there is nothing left
to surface.

## Examples

### Development defaults with production override

```yaml
mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-myapp}
```

In development, `MONGO_URI` is unset and the fallback is used. In production,
`MONGO_URI` is set via the environment.

### Secrets via environment

```yaml
providers:
  myoidc:
    type: oidc
    client_id: ${OIDC_CLIENT_ID}
    client_secret: ${OIDC_CLIENT_SECRET}
    discovery_url: ${OIDC_DISCOVERY_URL:-https://idp.example.com/.well-known/openid-configuration}
```

Each `${VAR}` here without a `:-default` aborts the build if the variable is unset.
The resolved values are baked into the output: `client_secret` is a build-time value,
not a runtime secret. For a public client, drop the `client_secret` line entirely
(it is optional). See [OIDC provider](../providers/oidc.md#fields).

## Edge Cases

- **`${VAR}` with unset variable.** Error `INTERPOLATION_MISSING_VAR`. Generation or
  the dev server stops with exit code 1.

- **`${VAR:-default}` with empty string.** If `VAR` is set to an empty string, the
  empty string is used -- NOT the fallback. The fallback only applies when `VAR` is
  completely unset.

- **The result stays a string.** Because substitution happens on parsed string
  scalars, an expanded value is never re-parsed as YAML; `${PORT}` expanding to `8080`
  produces the string `"8080"`.

- **Nested interpolation.** `${${INNER}}` is NOT supported as a single token; the
  inner `${INNER}` is resolved first, then the outer text is scanned again only as
  plain text. Do not rely on building a variable name from another variable.

- **Multiple variables in one value.** `${A}/${B}` is supported. Each `${...}` is
  resolved independently.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| Required variable not set | `INTERPOLATION_MISSING_VAR` | `Environment variable 'X' is required` |

The error includes a `path` field indicating where in the spec the unresolved
variable was found (e.g. `mongo.uri`) and a `hint`: `Set X or use ${X:-default}`.

## See Also

- [Auth overview](../auth/overview.md) -- for `JWT_SECRET`, `JWT_EXPIRATION_HOURS`, and `PASSWORD_HASH_ROUNDS`
- [Password provider](../auth/password-provider.md) -- for JWT token configuration
- [Mongo configuration](./mongo.md) -- for `mongo.uri` / `mongo.database` defaults and runtime overrides
- [API configuration](./api.md) -- for `basePath` / `version` and the resulting URLs
