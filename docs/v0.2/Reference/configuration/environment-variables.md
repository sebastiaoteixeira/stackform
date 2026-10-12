---
title: "Environment Variables and Interpolation"
description: Substitutes environment variable values into YAML string scalars after the YAML is parsed and before schema validation, plus the runtime variables the generated backend, the dev server, and a Docker deploy read directly -- including the JWT and provider client secrets the backend reads at run time via pydantic SecretStr settings.
---

There are two distinct ways environment variables reach a generated app, and they do
not overlap:

1. **Spec interpolation (build time).** `${VAR}` or `${VAR:-default}` inside any
   string value in the YAML spec is a build-time macro. It is resolved by the parser
   from the environment when the spec is loaded -- for both `stackform build` and
   `stackform run` -- and the resolved value is baked into the output. Most fields are
   baked this way, with one exception: a provider's `client_secret` is never baked as
   a code literal. The generator routes it to a per-provider runtime setting
   (`<PROVIDER>_CLIENT_SECRET`) instead (see the **Secrets** note below).
2. **Runtime variables.** The generated backend, the `stackform run` dev server, and
   a generated Docker deploy read a fixed set of variables (listed under
   [Runtime variables](#runtime-variables)) directly from the process environment at
   run time. These are read by the generated *code*, not by spec interpolation, and
   are never written in the spec. Secret-typed settings (`JWT_SECRET`, each
   confidential provider's `<PROVIDER>_CLIENT_SECRET`) are pydantic `SecretStr`
   fields, read in code via `settings.<NAME>.get_secret_value()`.

> **Secrets.** A provider `client_secret` is **not** baked into the artifact. When a
> confidential OIDC provider declares a `client_secret`, the generator emits a
> `<PROVIDER>_CLIENT_SECRET` env var (for a provider named `keycloak`, that is
> `KEYCLOAK_CLIENT_SECRET`) backed by a pydantic `SecretStr` setting, and the token
> exchange reads it at run time with
> `settings.<PROVIDER>_CLIENT_SECRET.get_secret_value()`. The literal secret must
> never live in the spec: write only a placeholder there (or omit the field) and
> provide the real value through the runtime environment. The same applies to
> `JWT_SECRET`. Earlier prerelease builds baked `client_secret` into the output as a
> literal; that no longer happens.

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

### Generated backend (`stackform build`, fastapi/raw targets)

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string. |
| `MONGO_DB` | `yaml_api` | MongoDB database name. |
| `JWT_SECRET` | *(generated)* | HMAC key for JWT signing (HS256), a `SecretStr` setting. The generated backend bundle ships a `.env` with a real value (`secrets.token_urlsafe`), so a fresh bundle runs without manual setup; override it for production. |
| `<PROVIDER>_CLIENT_SECRET` | *(none)* | OAuth2 client secret for each confidential OIDC provider (e.g. `KEYCLOAK_CLIENT_SECRET` for a provider named `keycloak`), a `SecretStr` setting read at run time via `settings.<PROVIDER>_CLIENT_SECRET.get_secret_value()`. Emitted only when the provider declares a `client_secret`. |
| `JWT_EXPIRATION_HOURS` | `24` | JWT token lifetime in hours. |
| `PASSWORD_HASH_ROUNDS` | `390000` | PBKDF2-HMAC-SHA256 iteration count for password hashing. |
| `FRONTEND_URL` | `""` | Base URL the OIDC callback redirects to (`{FRONTEND_URL}/auth/callback?code=...`). Falls back to the request base URL when unset. |
| `HOST` | `127.0.0.1` | Host the generated `app.py` binds to when run directly. |
| `PORT` | `api.port` (or `8000`) | Port the generated `app.py` binds to when run directly. |

The compile-time `mongo.uri` / `mongo.database` from the spec are only baked into the
Docker deploy defaults; the generated backend itself always reads `MONGO_URI` /
`MONGO_DB` at run time, falling back to the values above.

**Warning:** `JWT_SECRET` is a secret. The generated backend bundle ships a `.env`
with a unique generated value (see [Generated `.env` /
`.env.example`](#generated-env--envexample)), so a fresh bundle starts without
manual setup -- but that value is meant for development. Set a strong random value
(for example `openssl rand -hex 32`) for any non-development deployment. A generated
Docker deploy never bakes a secret into the bundle; it generates one at deploy time
(see [Docker deploy](#docker-deploy-stackform-build--deploy)).

### `stackform run` dev server

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
stackform run myapp.yaml --host 0.0.0.0 -p 8000
```

### Docker deploy (`stackform build ... deploy`)

The generated `docker-compose.yml` exposes these for `docker compose`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://mongodb:27017` | Backend MongoDB connection string inside the compose network. |
| `MONGO_DB` | `mongo.database` from the spec | Backend MongoDB database name. |
| `APP_PORT` | `deploy.port` | Host port mapped to the backend container. |
| `FRONTEND_PORT` | `80` | Host port mapped to the frontend container. |
| `VITE_API_BASE_URL` | `http://localhost:<port>/api/v1` | API base URL baked into the built frontend. |
| `BACKEND_URL` | `http://app:<port>` | Upstream the frontend's nginx proxies to (set by the container entrypoint). |
| `JWT_SECRET` | *(deploy-time)* | App JWT signing secret. Referenced as a bare `${JWT_SECRET}`; generated at deploy time by Ansible (see below). |
| `<PROVIDER>_CLIENT_SECRET` | *(deploy-time)* | Each confidential OIDC provider's client secret (e.g. `KEYCLOAK_CLIENT_SECRET`). Referenced as a bare `${VAR}`; generated at deploy time by Ansible (see below). |

#### Secrets in the generated deploy

Nothing secret is baked into the deploy bundle. The generated `deploy/` is an Ansible
playbook (`playbook.yml`, `inventory.yml`, `roles/`) plus the `docker-compose.yml`.
In compose, each secret is referenced as a **bare** `${VAR}` (no `:-<default>`
fallback) and the app service loads them through `env_file: .env`; non-secret
datastore variables keep their `${VAR:-default}` form.

Secrets are generated at **deploy time**, not generation time. The Ansible app role
produces a value for each secret with the `password` lookup
(`lookup('ansible.builtin.password', playbook_dir + '/.secrets/<NAME> ...')`), which
persists it under the playbook's `.secrets/` directory so reruns are idempotent. A
template task then renders the remote `/opt/<name>/.env` (mode `0600`) from those
values, and `docker compose` reads it via `env_file`. The `.secrets/` directory and
the remote `.env` are the only places the plaintext secret ever exists.

This currently covers the framework secrets the generated code reads (`JWT_SECRET`
and each confidential provider's `<PROVIDER>_CLIENT_SECRET`). Any additional runtime
variables your backend needs are declared explicitly in the spec's `deploy.env_vars`
list and emitted with an empty default for you to fill.

## Generated `.env` / `.env.example`

### Backend bundle

A plain backend build (`stackform build`, fastapi target) -- with or without a
`deploy:` block -- writes both files next to the backend:

- `.env` lists every runtime setting with real values: secret-typed settings
  (`JWT_SECRET`, each `<PROVIDER>_CLIENT_SECRET`) get a generated value via
  `secrets.token_urlsafe`, and other settings get their default. So a freshly built
  backend bundle runs without exporting `JWT_SECRET` yourself.
- `.env.example` lists the same keys but with placeholders for secrets
  (`JWT_SECRET=<jwt_secret>`, `KEYCLOAK_CLIENT_SECRET=<keycloak_client_secret>`),
  ready to commit as a template.

A provider `client_secret` you wrote in the spec is **not** copied here as a literal:
its value is whatever the runtime `<PROVIDER>_CLIENT_SECRET` env var carries, so set
the real secret in `.env` before going to production.

### Deploy bundle

The deploy bundle does **not** ship a secret-filled `.env`. Its remote `.env` is
rendered on the target host at deploy time by Ansible from the values under the
playbook's `.secrets/` directory (mode `0600`); see [Secrets in the generated
deploy](#secrets-in-the-generated-deploy). Nothing secret is baked into the bundle.

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
`client_id` and `discovery_url` are baked into the output. `client_secret` is the
exception: it is **not** baked. Its presence makes the generator emit a
`<PROVIDER>_CLIENT_SECRET` env var (here `MYOIDC_CLIENT_SECRET`) backed by a
`SecretStr` setting, read at run time. The `${OIDC_CLIENT_SECRET}` placeholder above
just marks the field as confidential; supply the real secret through the runtime
environment, never in the spec. For a public client, drop the `client_secret` line
entirely (it is optional). See [OIDC provider](../providers/oidc.md#fields).

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
