---
title: Troubleshooting
description: Common build, run, and request errors and how to fix them.
---

Errors fall into three groups: build/validation errors (raised by `yaml-api build` and
`yaml-api run` while reading your spec), runtime startup errors (MongoDB, environment
variables), and HTTP responses from the generated app. The examples below assume this
`api:` block, so the URLs are reproducible:

```yaml
api:
  basePath: /api
  version: v1
```

With that block, routes are mounted under `/api/v1` (for example `POST /api/v1/notes`).
Omit `version` and the segment disappears (`/api/notes`); omit the whole `api:` block and
`basePath` still defaults to `/api`.

## Build and validation errors

`yaml-api build` and `yaml-api run` validate your spec before generating or serving
anything. By default errors print in GCC style to stderr and exit with code 1:

```text
myapp.yaml:12:entities.note.fields: error: ... [SCHEMA_VALIDATION_ERROR]
   12 |     title: { type: string }
        ^
1 error generated.
```

Pass `--json` to get machine-readable output instead, one object per error:

```json
[
  {"code": "SCHEMA_VALIDATION_ERROR", "message": "...", "path": "entities.note.fields", "hint": "..."}
]
```

Common codes:

- `UNSUPPORTED_VERSION` -- the top-level `version:` is not a supported dialect. Set
  `version: "0.2"` (omitting it defaults to `0.1`, which has fewer features).
- `YAML_PARSE_ERROR` -- the file is not valid YAML. Check indentation, missing colons,
  and tabs (use spaces).
- `YAML_ROOT_INVALID` -- the document parsed but the top level is not a mapping.
- `SCHEMA_VALIDATION_ERROR` -- valid YAML, but the structure does not match the schema.
  Fix the field name or type at the `path` shown.
- `ID_FIELD_MISSING` / `ID_FIELD_MULTIPLE` -- an entity must declare exactly one
  `type: id` field (or a natural `pk:`). Zero or two `id` fields are rejected.
- `CRUD_OPERATION_INVALID` -- a `repositories.<name>.crud` list contains a value that is
  not one of `list`, `get`, `create`, `update`, `replace`, `delete`.
- `OPERATION_MISSING_QUERY_OR_HANDLER` -- a custom `repositories.<name>.operations.<op>`
  declares neither a `query:` nor a `handler:`.
- `QUERY_COMMAND_UNKNOWN` / `QUERY_MISSING_COLLECTION` -- a query op uses an unknown
  command or targets no collection (the repository has no entity and no
  `query.collection`).
- `ACCESS_AMBIGUOUS_ROLE` / `ACCESS_NO_AUTH_ENTITY` / `ACCESS_UNKNOWN_ENTITY` -- an access
  rule names a role that matches more than one identity entity, references roles when no
  `type: auth` entity exists, or names an entity that does not exist.
- `AUTH_PASSWORD_FIELD_FORBIDDEN` / `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN` -- you declared a
  `password` or `passwordHash` field explicitly. Password handling is implicit for
  password auth; do not declare these.
- `WHEN_EXPR_INVALID` / `WHEN_OPERAND_INVALID` / `WHEN_OPERAND_MISSING` /
  `WHEN_LIST_INVALID` -- a `when:` expression is malformed. See the gotchas below.

### When-expression gotchas

- Use the word `equals`, not `==`. Supported operators: `equals`, `not equals`, `and`,
  `or`, `not`, `in`, `not in`.
- Operands are field references and single-quoted string literals (for example
  `principal.sub equals document.ownerId`, or `document.status equals 'published'`).
  Bare `true`/`false` literals are not accepted; compare against a quoted string instead.
- A stored field on the authenticated record is read via `principal.record.<field>`
  (bare `principal` is the subject id from the token).
- Keywords are case-insensitive, but there is no parenthesis grouping; combine clauses
  with `and`/`or`.

## MongoDB connection refused

The generated backend connects to MongoDB lazily, so a bad connection surfaces on the
first query (not at startup), as a `pymongo` timeout:

```text
pymongo.errors.ServerSelectionTimeoutError: localhost:27017: [Errno 111] Connection refused
```

MongoDB is not reachable. Fix it depending on how you are running the app:

- `yaml-api run` (dev server): start MongoDB yourself, then re-run. The dev server reads
  `YAML_API_MONGO_URI` (default `mongodb://localhost:27017`) and `YAML_API_MONGO_DB`
  (default `yaml_api`).
- Generated Docker deploy: `docker compose up -d` from the generated `deploy/`
  directory. Mongo runs as the `mongodb` service; the backend reads `MONGO_URI` /
  `MONGO_DB` from the compose environment.
- Generated backend run directly: set `MONGO_URI` / `MONGO_DB` and point them at a
  running MongoDB.

## Missing environment variable

```text
myapp.yaml:7:mongo.uri: error: Environment variable 'MONGO_URI' is required [INTERPOLATION_MISSING_VAR]
```

A `${VAR_NAME}` in your spec references an environment variable that is not set.
Interpolation runs while the spec is read (during both `build` and `run`) and aborts with
exit code 1. Either set the variable, or give it a default with `${VAR_NAME:-default}`.

## 422 Unprocessable Entity

A 422 means the request body did not validate. There are two shapes.

Pydantic model validation (missing field, wrong type) returns a `detail` array:

```bash
curl -X POST http://localhost:8000/api/v1/notes \
  -H 'Content-Type: application/json' \
  -d '{"body": "Hello"}'
```

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "title"],
      "msg": "Field required",
      "input": {"body": "Hello"}
    }
  ]
}
```

Each `detail[].loc` points at the offending field; `["body", "title"]` means `title` is
missing. Include all required fields and fix the request.

Service-layer validation returns a flat message instead:

```json
{"detail": "Missing required field: title"}
```

You may also see `{"detail": "Password must be a non-empty string"}` for password auth,
and (on the `yaml-api run` dev server) `{"detail": "Unknown fields: foo"}` for fields not
declared on the entity, or `{"detail": "Field 'status' must be one of: draft, published"}`
for an enum value outside the declared `values`.

## 404 Not Found

```json
{"detail": "Resource not found"}
```

The id in the path does not match any document. For get/update/replace/delete the record
is fetched first, so a missing record returns 404 before any ownership rule is checked.

## 401 Unauthorized

```json
{"detail": "Unauthorized"}
```

The route requires a principal and none was resolved. Provide one of the accepted
credentials:

```text
Authorization: Bearer <jwt>      # password/SSO login token
X-API-Key: <key>                 # API-key identity (also accepted as Bearer)
Authorization: Basic <base64>    # HTTP Basic, password identity
```

They are tried in that order: Bearer JWT, then API key, then HTTP Basic. Get a JWT from
the login endpoint -- for an identity collection `users` with the `api:` block above:

```bash
curl -X POST http://localhost:8000/api/v1/users/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "a@example.com", "password": "secret"}'
```

A successful login returns `{"token": "...", "user": {...}}` (the `user` object strips
`password`, `_id`, and `_auth`). The login route is `401 {"detail": "Invalid credentials"}`
on a bad password.

Note: `register` and `login` are not generated unless you enable them:

```yaml
api:
  operations:
    auth:
      register: true
      login: true
```

## 403 Forbidden

```json
{"detail": "Forbidden"}
```

You are authenticated but an access rule denied the request -- the wrong role, an
`identity:<entity>` scope you are not in, or an ownership/`when` rule that did not match.
Check the access rules on the controller for that operation.

> **Enforcement status**
>
> Roles (exact match), `identity:<entity>` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `yaml-api run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

## JWT_SECRET warning

In production, always set the `JWT_SECRET` environment variable to a strong random value.
The default (`yaml-api-dev-secret-change-me`) is insecure and only suitable for
development. Related auth env vars: `JWT_EXPIRATION_HOURS` (default 24) and
`PASSWORD_HASH_ROUNDS` (default 390000).

```bash
export JWT_SECRET=$(openssl rand -hex 32)
yaml-api run myapp.yaml
```

## Frontend or deploy build fails

`yaml-api build <file> frontend` and `yaml-api build <file> deploy` require the matching
block in the spec, and exit 1 with one of:

- `Error: No 'ui' block found in the YAML spec.` -- add a `ui:` block (or run a plain
  `build`, which skips a missing frontend instead of failing).
- `Error: ui.frontend.pack is required.` -- set `ui.frontend.pack: generic`.
- `Error: No 'deploy' block found in the YAML spec.` -- add a `deploy:` block.

## SSO and external auth

External providers are attached through `auth.bindings` and need a reachable provider.
Common callback failures (status from `GET /api/v1/{collection}/auth/{provider}/callback`):

- `401 {"detail": "Token exchange failed"}` -- the authorization code could not be
  exchanged. Check `client_id`, `client_secret`, and the redirect URI registered with the
  provider; the callback URI is derived from your `basePath`/`version`.
- `401 {"detail": "Failed to fetch user info"}` -- the access token was rejected by the
  provider's userinfo endpoint, or the token expired.
- `403 {"detail": "User not found and auto-provisioning is disabled"}` -- no matching
  local user and the binding set `auto_provision: false` (it defaults to true).

On success the callback mints an app JWT and redirects to
`{FRONTEND_URL}/auth/callback?token=<jwt>`. Set `FRONTEND_URL` so the redirect reaches
your UI; if unset it falls back to the backend's own base URL. The generated login page
discovers available providers from `GET /api/v1/{collection}/auth/providers`.
