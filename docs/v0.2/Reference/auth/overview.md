---
title: "Auth Overview"
description: Declares an entity as an identity provider, enabling authentication, token issuance, and role-based access control.
---

Declares an entity as an identity provider, enabling authentication, token issuance, and role-based access control.

## Syntax

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user
```

A record's roles come from one of two places:

- **A role field.** `auth.roles` names an `enum` field of the entity. Its `values:`
  are the roles and its `default:` is the role a new record gets.
- **Managed roles.** An entity-level `roles: { values, default, hierarchy }` block
  keeps the roles in the record's internal `_auth` namespace, outside the API's
  fields. See [roles overview](../roles/overview.md).

## Behavior

- **Parse time:** declaring `type: auth` requires an `auth:` block (schema validation).
  A `password` or `apiKey` entity must set `auth.identifier`
  (`AUTH_IDENTIFIER_REQUIRED`) to one of its fields
  (`AUTH_IDENTIFIER_FIELD_NOT_FOUND`), and an `apiKey` entity must declare an
  `apiKey` field (`AUTH_API_KEY_FIELD_MISSING`). If `auth.roles` is set, the named
  field must exist (`AUTH_ROLES_FIELD_NOT_FOUND`) and be of `type: enum`
  (`AUTH_ROLES_FIELD_NOT_ENUM`).
- **Compile time:** register and login endpoints are generated only when enabled via
  `api.operations.auth: { register: true, login: true }` (off by default). For
  password-based auth, a `password` input is injected into the create model.
- **Runtime:** principals authenticated via this entity receive a JWT whose `sub` is the
  identity record's primary-key value. The entity participates in access rules as
  `<entityName>:*` and `<entityName>:<role>`, and a role also matches every role its
  hierarchy includes. A request that fails every rule gets 401 when it carries no
  valid credentials and 403 otherwise; a missing record answers 404 before ownership
  is checked.
- **Role grants:** a caller sets a role field only to roles it holds itself. On
  create, a record naming other roles gets the default role instead; on update, the
  role change is dropped. Managed roles are never written through the API: a new
  record gets `roles.default`.

## Options

### `type: auth`

Marks the entity as an identity provider. Only valid value: `"auth"`. The default for
any entity is `base`.

Effects:
- Generates `register` and `login` endpoints when `api.operations.auth` enables them.
- Principals authenticated via this entity receive a JWT with `sub` set to the record's
  primary-key value.
- The entity participates in access rules as `<entityName>:*` and
  `<entityName>:<role>`.

### `auth:` block

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `identifier` | for `password` and `apiKey`, and for names in `via` | string (field name) | The field used as the login username (for password) or the matched value. |
| `via` | no | string, list of strings, or list of objects | The providers users sign in through (see below). Without it the entity signs no one in. |
| `roles` | no | string (field name) | Names an `enum` field that holds the principal's role. See [roles overview](../roles/overview.md). |

`via` accepts a provider name, a list of names, or a list of binding objects. A
name uses the entity's `auth.identifier`; `password` and `apiKey` are built in, and
any other name must be a key of `providers:` (`AUTH_VIA_UNKNOWN_PROVIDER`). A
binding object takes:

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `provider` | yes | string | `password`, `apiKey`, or the name of a provider declared under `providers:` (`BINDING_PROVIDER_NOT_FOUND`). |
| `identifier` | no | string (field name) | Field matched against the provider's principal. Defaults to `auth.identifier`, and must be a field of the entity (`BINDING_IDENTIFIER_FIELD_NOT_FOUND`). |
| `claim_mapping` | no | map (string to string) | Maps entity fields to provider claims. See [claim mapping](./claim-mapping.md). |
| `auto_provision` | no | boolean | Create a local record on first login when no match exists. Defaults to `true`. |
| `relations` | no | map | Fills a foreign key from a record whose fields match claims. See [claim mapping](./claim-mapping.md). |

A list holds either names or binding objects; name a built-in provider in a list of
objects as `- provider: password`.

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via:
        - provider: password
        - provider: google
          identifier: email
          claim_mapping: { email: email, displayName: name }
          auto_provision: true
      roles: role
```

### Role hierarchy

A hierarchy is declared in the entity's managed `roles:` block. Each key lists the
roles it includes, transitively:

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
    roles:
      values: [admin, moderator, user]
      default: user
      hierarchy:
        admin: [moderator]
        moderator: [user]
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
```

A principal with role `admin` then matches rules for `user:moderator` and
`user:user` too. See [roles hierarchy](../roles/hierarchy.md).

## How a request is authenticated

The generated backend resolves a principal by trying credentials in this order:

1. **Bearer JWT** (`Authorization: Bearer <jwt>`) -- used for password-based entities.
   The token carries only `sub` and `identity_collection`; the identity record and its
   roles are loaded from the datastore on every request, so role changes apply immediately.
2. **API key** (`X-API-Key: <key>`, or `Authorization: Bearer <key>`) -- matched against
   the top-level `apiKey` field of each `apiKey` entity.
3. **HTTP Basic** (`Authorization: Basic <base64(identifier:password)>`) -- the identifier
   is matched against the `auth.identifier` field and the password verified against the
   stored hash.

The resolved principal exposes:
- `principal.sub` -- the primary-key value of the matched record.
- `principal.identity_collection` -- the entity/collection that matched.
- `principal.roles` -- read from the `auth.roles` enum field, or from the managed
  roles under `_auth` when the entity declares a `roles:` block.
- `principal.record` -- the matched record. Stored fields are referenced in `when` rules
  as `principal.record.<field>`. In the generated FastAPI/DRF backends this is the raw
  stored record (including the internal `_auth` namespace); the `stackform run` dev
  server passes a sanitized record.

## Internal Storage

For password auth, the password is never stored; only the hash is persisted under an
internal `_auth` namespace. The hash format is
`pbkdf2$sha256$<rounds>$<salt>$<hash>` (PBKDF2-HMAC-SHA256, default 390000 rounds,
configurable via `PASSWORD_HASH_ROUNDS`).

A role field lives in the record like any other field. Managed roles live under
`_auth.roles` and are read from there at request time.

```
# Stored record (internal)
{ "id": "abc", "email": "alice@example.com", "role": "admin",
  "_auth": { "passwordHash": "pbkdf2$sha256$390000$..." } }
```

The login response and the `principal.record` seen by the `run` dev server strip
`password`, `_id`, and `_auth`. In the generated FastAPI/DRF backends, `principal.record`
is the raw document; do not rely on access rules to hide `_auth` there.

## Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `JWT_SECRET` | dev placeholder | HS256 signing secret for issued tokens. Set a strong value in production. |
| `JWT_EXPIRATION_HOURS` | `24` | Token lifetime in hours when `session.ttl` is unset; `session.ttl` sets it in seconds. |
| `PASSWORD_HASH_ROUNDS` | `390000` | PBKDF2-SHA256 iteration count for password hashing. |

## Examples

### Single auth entity with password and roles

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  operations:
    auth:
      register: true
      login: true

entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user
```

Login: `POST /api/v1/users/login` returns `{"token": "...", "user": {...}}` (the user
excludes `password`, `_id`, and `_auth`).

### API key auth entity

The API key is a plain top-level `apiKey` string field; it is matched verbatim at request
time. There is no auto-generation -- the client supplies the key on creation.

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

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

> **Security:** `apiKey` is an ordinary field and is returned in CRUD responses; restrict
> read access to this entity. See [API key provider](./apikey-provider.md).

### Multiple auth entities

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
    fields:
      id: { type: id }
      clientId: { type: string, required: true, unique: true }
      apiKey: { type: string, required: true }
```

With multiple auth entities, role-bearing access rules must use the entity prefix:

```yaml
access: user:admin           # required -- unscoped "admin" is a parse error
access: apiClient:enterprise
```

## Edge Cases

- **Multiple auth entities: Bearer token resolution.** When multiple auth entities exist,
  the JWT carries its `identity_collection`, so resolution targets that collection
  directly. API-key and Basic credentials are tried against each entity in turn; the first
  match wins.

- **Multiple auth entities: scoped syntax required.** Role access rules must use scoped
  syntax (`user:admin`, not just `admin`). An unscoped role name is a parse error
  (`ACCESS_AMBIGUOUS_ROLE`) when more than one auth entity exists.

- **Single auth entity: scoped and unscoped both work.** With a single auth entity, both
  `admin` and `user:admin` are valid in access rules.

- **`identifier` field should have `unique: true`.** If the identifier field is not unique,
  login may match the wrong record (first found). No parse error is raised, but this is a
  configuration mistake.

- **Password is never stored.** Only `_auth.passwordHash` is persisted, using
  PBKDF2-SHA256 with 390000 iterations by default.

- **Entity without roles.** With neither `auth.roles` nor a `roles:` block, the
  entity still authenticates principals but has no roles. `access: public`, `access: "*"`, and `access: user:*` still work;
  `access: user:admin` will never match because no role values exist.

## Errors

| Condition | Error code | Message |
|-----------|-----------|---------|
| `type: auth` without `auth:` block | schema validation | `auth` is required when type is "auth" |
| `auth.roles` names a missing field | `AUTH_ROLES_FIELD_NOT_FOUND` | "Roles field 'X' not found in entity 'Y'" |
| `auth.roles` field is not an enum | `AUTH_ROLES_FIELD_NOT_ENUM` | "Roles field 'X' must be of type 'enum'" |
| `password` or `apiKey` entity without `auth.identifier` | `AUTH_IDENTIFIER_REQUIRED` | "Auth entity 'Y' uses via password but declares no identifier" |
| `auth.identifier` names a missing field | `AUTH_IDENTIFIER_FIELD_NOT_FOUND` | "Auth identifier 'X' not found in entity 'Y'" |
| `apiKey` entity without an `apiKey` field | `AUTH_API_KEY_FIELD_MISSING` | "Auth entity 'Y' uses via apiKey but declares no apiKey field" |
| `via` names an undeclared provider | `AUTH_VIA_UNKNOWN_PROVIDER` | "Auth entity 'Y' uses via 'X', which is not a declared provider" |
| Binding names an undeclared provider | `BINDING_PROVIDER_NOT_FOUND` | "Auth entity 'Y' binds undeclared provider 'X'" |
| Binding `identifier` names a missing field | `BINDING_IDENTIFIER_FIELD_NOT_FOUND` | "Binding identifier 'X' not found in entity 'Y'" |
| `roles.default` not in `roles.values` | `ROLES_DEFAULT_UNKNOWN_ROLE` | "Default role 'X' is not one of the declared roles" |
| `roles.hierarchy` names an undeclared role | `ROLES_HIERARCHY_UNKNOWN_ROLE` | "Role hierarchy references undeclared role 'X'" |
| `roles.hierarchy` is cyclic | `ROLES_HIERARCHY_CYCLE` | "Role hierarchy for 'Y' is cyclic through 'X'" |
| `password` declared in `fields:` | `AUTH_PASSWORD_FIELD_FORBIDDEN` | "Password input is implicit when auth.via includes password" |
| `passwordHash` declared in `fields:` | `AUTH_PASSWORD_HASH_FIELD_FORBIDDEN` | "passwordHash is implicit storage when auth.via includes password" |
| Unscoped role with multiple auth entities | `ACCESS_AMBIGUOUS_ROLE` | "Unscoped role 'X' is ambiguous with multiple auth entities; use 'entity:X'" |
| Role used with no auth entity | `ACCESS_NO_AUTH_ENTITY` | "Cannot use role 'X' without auth entities" |

## See Also

- [Password provider](./password-provider.md)
- [API key provider](./apikey-provider.md)
- [Claim mapping](./claim-mapping.md)
- [Roles overview](../roles/overview.md)
- [Roles hierarchy](../roles/hierarchy.md)
- [Access control](../controllers/access-control.md)
