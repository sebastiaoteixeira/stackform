---
title: "API Key Provider"
description: Machine-to-machine authentication via a static API key stored on the identity record and passed in a request header.
---

Enables machine-to-machine authentication via a static API key. The key is stored
as a plain `apiKey` field on the identity record and presented on every request in
the `X-API-Key` header (or as a bearer token).

## Syntax

The API key is matched against a top-level `apiKey` field, so the identity entity
must declare one. A full working spec wires the entity to a repository, a service,
and a controller:

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

entities:
  myEntity:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      apiKey: { type: string, required: true }
      name: { type: string, required: true }
      active: { type: boolean, default: true }

repositories:
  myCollection:
    entity: myEntity

services:
  myCollection:
    repository: myCollection

controllers:
  myCollection:
    service: myCollection
    base_path: /my-collection
    access: authenticated
```

The resource name on every URL is the repository name (`myCollection`), composed with
the controller `base_path` and the `api:` block. With the block above, requests land
at `/api/v1/my-collection`.

## Behavior

- Generation time: a `type: auth` entity with `via: apiKey` produces an identity
  collection. There is no `register`/`login` step for API keys -- the key itself is
  the credential. To expose a `POST .../register` for creating client records, enable
  `api.operations.auth.register` (see [Login, SSO, and the token flow](./login-and-sso.md)).
- Runtime: on each request the backend reads the `X-API-Key` header (falling back to
  `Authorization: Bearer`), then scans the identity collection for a document whose
  top-level `apiKey` equals the presented value. On a match it builds a principal with
  `sub` set to the record's id field, `record` set to the full document, and `roles`
  taken from the entity's roles field (see Roles below).

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

## Options

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `identifier` | effectively required | string (field name) | Names the field that identifies the client (for example `clientId`). Not used for API key matching, but conventionally declared `unique: true`. |
| `via` | yes | string or list | Must include `apiKey`. A list (for example `[apiKey, password]`) enables more than one credential type on the same entity. |
| `roles` | no | string (field name) | Names an `enum` field whose value becomes the principal's role. See Roles. |

## Security: the API key is returned in responses

The `apiKey` field is an ordinary stored field. CRUD responses strip the internal
`_auth` namespace, `password`, and the Mongo `_id`, but they do NOT strip `apiKey`.
Any caller allowed to read a client record sees the key in plaintext. Lock down the
read operations accordingly -- for example require an admin role on `list`/`get`, or
remove those operations from the repository's `crud` set:

```yaml
repositories:
  myCollection:
    entity: myEntity
    crud: [create, get, delete]   # no list; restrict get to admins in the controller
```

There is no built-in key generation, hashing, or rotation. The client value is stored
verbatim; to rotate, update the record with a new `apiKey` via the update operation.

## Authentication flow

1. The client is created with a `clientId` and an `apiKey` value (you supply both).
2. On each request the client sends the key in the `X-API-Key` header, or as a bearer
   token in `Authorization: Bearer <key>`.
3. The backend looks up the client by matching the presented value against the stored
   `apiKey` field.
4. On a match a principal is resolved (`sub` = the record's id field value).

When the same entity also enables password auth, a presented `Authorization: Bearer`
value is tried as a JWT first; only if it is not a valid JWT is it treated as an API
key. To avoid that ambiguity, send API keys in the `X-API-Key` header.

## Creating a client

With `api.operations.auth.register` enabled, post to the controller's register route:

```json
POST /api/v1/my-collection/register
{
  "clientId": "my-client",
  "name": "My Client",
  "apiKey": "sk-abc123..."
}
```

Without the register operation, create client records through the standard create
operation (`POST /api/v1/my-collection`). Either way, the `apiKey` value is stored as a
top-level field on the document.

## Making authenticated requests

```bash
# Via X-API-Key header (preferred)
curl -H "X-API-Key: sk-abc123..." http://localhost:8000/api/v1/my-collection

# Via bearer token
curl -H "Authorization: Bearer sk-abc123..." http://localhost:8000/api/v1/my-collection
```

## Generated endpoints

CRUD routes follow the repository's enabled operations. All six operations
(list, get, create, update, replace, delete) are enabled by default; opt out per
repository with a `crud:` list. The `register` route appears only when
`api.operations.auth.register` is enabled.

| Method | Path | Default | Description |
|--------|------|---------|-------------|
| POST | `/api/v1/my-collection/register` | only if `operations.auth.register` is on | Create a client record |
| POST | `/api/v1/my-collection` | on | Create a client record (standard create) |
| GET | `/api/v1/my-collection` | on | List clients |
| GET | `/api/v1/my-collection/{id}` | on | Get a client |
| PATCH | `/api/v1/my-collection/{id}` | on | Update a client |
| PUT | `/api/v1/my-collection/{id}` | on | Replace a client |
| DELETE | `/api/v1/my-collection/{id}` | on | Delete a client |

There is no separate login step for API keys: the key is the credential on every
request.

## OpenAPI security schemes

When an identity uses `apiKey`, the generated OpenAPI document advertises two schemes
on non-public routes:

- `ApiKeyAuth`: `apiKey` in header `X-API-Key`.
- `BearerAuth`: HTTP bearer (the same key sent as `Authorization: Bearer`).

If the entity also enables password auth, `BearerAuth` is additionally used for JWTs,
which the backend tries before treating a bearer value as an API key.

## Roles

The entity-level `roles: { values, default, hierarchy }` block is parsed but not wired
into the backend in v0.2 -- it does not assign a default role on create and its
hierarchy is inert. To attach a role to an API client, declare an `enum` field and
point `auth.roles` at it:

```yaml
entities:
  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
      roles: tier
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      apiKey: { type: string, required: true }
      name: { type: string, required: true }
      tier:
        type: enum
        values: [free, premium, enterprise]
        default: free
```

The principal's role is read from the named field (`tier` here). Access rules then
match it exactly with `entity:role`, for example `apiClient:enterprise`. Role
hierarchy is not applied during enforcement; only exact matches pass.

## Errors

| Condition | HTTP Status | Response |
|-----------|-------------|----------|
| Invalid or unknown API key | 401 | `{"detail": "Unauthorized"}` |
| Missing credentials on a protected route | 401 | `{"detail": "Unauthorized"}` |
| Authenticated but role/scope not allowed | 403 | `{"detail": "<reason>"}` |
| Record not found before an ownership check | 404 | `{"detail": "Resource not found"}` |

## Differences from the password provider

| Aspect | password | apiKey |
|--------|----------|--------|
| Credential | Username + password -> JWT | Static key on every request |
| Token lifetime | JWT expiry (`JWT_EXPIRATION_HOURS`) | Indefinite (until the key is changed or the record is deleted) |
| Login endpoint | Yes, when `operations.auth.login` is enabled | None |
| Stored secret | `_auth.passwordHash` (stripped from responses) | Plain `apiKey` field (NOT stripped) |
| Primary use case | Human users | Services, scripts, integrations |

## See Also

- [Auth overview](./overview.md)
- [Authentication required by default](./auth-required-by-default.md)
- [Password provider](./password-provider.md)
- [Login, SSO, and the token flow](./login-and-sso.md)
- [Access control](../controllers/access-control.md)
