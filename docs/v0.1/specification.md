---
title: Specification
---

Status: Draft v0.1  
Target: YAML-driven API engine with a transport-agnostic core and compiled step pipelines.

## 1. Design Goals and Scope (v0.1)

This specification defines a stable, implementation-oriented YAML contract for generating CRUD APIs over MongoDB.

### 1.1 Goals

- The spec **MUST** be deterministic: the same YAML input produces equivalent behavior in interpreted and compiled modes.
- The spec **MUST** be compile-friendly: static declarations are validated and lowered into executable pipelines at startup/build time.
- The core model **MUST** remain transport-agnostic: route/operation intents are protocol-neutral, then adapted to REST in v0.1.
- The spec **SHOULD** optimize for safe defaults (private by default, explicit public access, explicit write permissions).
- The spec **SHOULD** keep YAML expressive enough for common use cases without becoming a general-purpose language.

### 1.2 In Scope for v0.1

- Collection and field modeling with core constraints.
- Auth collections with collection-local auth configuration.
- Generated CRUD operations with per-operation toggles.
- Access-rule declarations compilable to step pipelines.
- Security and CORS baseline configuration.
- Startup/build-time validation and actionable error reporting.

### 1.3 Out of Scope for v0.1

- Full provider protocol config (OIDC/OAuth/SAML runtime details).
- Custom function runtimes and transactional function semantics.
- Realtime subscriptions, webhooks, and advanced lifecycle logic DSL.

## 2. Interpolation Semantics

Interpolation is supported in scalar string values.

### 2.1 Supported Forms

- `${VAR}`: required environment variable.
- `${VAR:-default}`: optional environment variable with fallback default.

### 2.2 Resolution Rules

- Resolution **MUST** happen before schema validation that depends on interpolated values.
- `${VAR}` **MUST** fail validation if `VAR` is unset.
- `${VAR:-default}` **MUST** resolve to `default` when `VAR` is unset.
- Empty-string values **MUST** be treated as set values unless an implementation profile states otherwise.
- Interpolation **MUST NOT** be recursively evaluated inside resolved values in v0.1.

### 2.3 Future Provider References (Reserved)

v0.1 reserves provider-based references for future versions. The following syntax is reserved and **MUST** be rejected in v0.1 unless a feature flag enables it:

- `${{ env.VAR }}`
- `${{ secret.vault.path#key }}`
- `${{ secret.aws-sm.name#jsonKey }}`

## 3. Top-Level Schema

Top-level document type: object.

### 3.1 Sections

| Section | Type | Required | Description |
|---|---|---:|---|
| `version` | string | YES | Specification/API config version string (e.g. `"0.1"`, `"v1"`). |
| `api` | object | NO | API generation defaults and operation toggles (defaults apply when omitted). |
| `collections` | map<string, CollectionConfig> | YES | Declared data models. |
| `security` | object | NO | CORS, headers, and secret-redaction controls. |
| `access` | object | NO | Reusable access rule fragments/options. |
| `options` | object | NO | Engine-level options (strictness/warnings policy). |

### 3.2 Unknown Keys

- Unknown top-level keys **SHOULD** trigger warnings by default.
- Strict mode **MAY** elevate unknown keys to errors.

## 4. Collection Schema

`collections` is a map keyed by collection name.

### 4.1 CollectionConfig

| Field | Type | Required | Default | Notes |
|---|---|---:|---|---|
| `type` | enum | NO | `base` | Collection category. v0.1 values: `base`, `auth`. |
| `fields` | map<string, FieldConfig> | YES | - | Field definitions. |
| `operations` | OperationsConfig | NO | inherit `api.operations.defaults` | Per-collection operation toggles. |
| `softDelete` | boolean | NO | `false` | Soft-delete behavior. |
| `indexes` | array<IndexConfig> | NO | `[]` | Optional index declarations. |

### 4.2 FieldConfig

| Field | Type | Required | Default | Constraints |
|---|---|---:|---|---|
| `type` | enum | YES | - | `string`, `number`, `boolean`, `datetime`, `enum`, `array`, `object`, `ref`, `id` |
| `required` | boolean | NO | `false` | Enforced on create; on update, only when field provided unless full replace. |
| `default` | any | NO | none | Must be type-compatible. |
| `unique` | boolean | NO | `false` | Implies unique index recommendation. |
| `min` | number | NO | none | Number lower bound. |
| `max` | number | NO | none | Number upper bound. |
| `minLength` | integer | NO | none | String lower bound. |
| `maxLength` | integer | NO | none | String upper bound. |
| `format` | enum | NO | none | `email`, `e164`, `uri`, `uuidv7`, `uuidv4` (v0.1 set). |
| `values` | array<string> | conditional | none | Required when `type: enum`. |
| `items` | FieldConfigLite | conditional | none | Required when `type: array`. |
| `properties` | map<string, FieldConfig> | NO | none | For typed object fields. |
| `additionalProperties` | boolean | NO | `false` | If true, object is schemaless-compatible. |
| `ref` | string | conditional | none | Required when `type: ref`; target collection name. |
| `store` | enum | NO | `id` | For refs: `id` or `embed`. |
| `expand` | object | NO | none | Expansion policy (`allowed`, `always`, `fields`, `maxDepth`). |

### 4.3 Field Validation Rules

- `min`/`max` **MUST** only apply to `number`.
- `minLength`/`maxLength` **MUST** only apply to `string`.
- `format` for `string` **MUST** be one of `email`, `e164`, `uri`.
- `format` for `id` **MAY** be `uuidv7` or `uuidv4`; default is `uuidv7`.
- Each collection **MUST** define exactly one top-level `type: id` field.
- `values` **MUST** be present and non-empty for `enum`.
- `items` **MUST** be present for `array`.
- `ref` **MUST** target an existing collection.
- `unique: true` fields **SHOULD** be reconciled with backend indexes at startup.

## 5. Identity and Authentication Schema

Collections are identity-capable when `collections.<name>.type` is set to `auth`.
Authentication settings are declared directly inside each auth collection at `collections.<name>.auth`.

### 5.1 Collection Auth Config

`collections.<name>.auth` schema (required when `collections.<name>.type: auth`):

| Field | Type | Required | Default |
|---|---|---:|---|
| `identifier` | string | YES | - |
| `via` | `password` OR `apiKey` OR array of those values | YES | - |

`via` accepts either a single method or multiple methods, for example:

- `via: password`
- `via: [password, apiKey]`

Rules:

- `identifier` **MUST** reference a field in the auth collection.
- `identifier` **SHOULD** be marked `unique: true`.
- `via` values **MUST** be canonical and case-sensitive: `password` and `apiKey`.
- API key authentication **MUST** use the standardized method name `apiKey`.
- Any other `via` value (including aliases such as `apikey`, `api_key`, or `api-key`) **MUST** fail validation.
- When `via` includes `password`, request body input `password` is implicit for create operations.
- When `via` includes `password`, storage field `passwordHash` is implicit and **MUST NOT** be declared in YAML fields.
- Credential material (password hash, reset tokens, API keys) **MUST NOT** be returned by generated endpoints.

## 6. API Operation Generation Schema

### 6.1 Global API Section

`api` is optional in v0.1. When omitted, engines MUST use defaults.

`api` schema:

| Field | Type | Required | Default |
|---|---|---:|---|
| `basePath` | string | NO | `/api` |
| `version` | string | NO | none |
| `pagination` | object | NO | `{ defaultPageSize: 20, maxPageSize: 100 }` |
| `operations` | object | NO | `{ defaults: { list: true, get: true, create: true, update: true, replace: true, delete: true } }` |

`api.operations.defaults` schema:

| Operation | Type | Default |
|---|---|---|
| `list` | boolean | `true` |
| `get` | boolean | `true` |
| `create` | boolean | `true` |
| `update` | boolean | `true` |
| `replace` | boolean | `true` |
| `delete` | boolean | `true` |

### 6.2 Per-Collection Overrides

- `collections.<name>.operations` **MAY** override any global default.
- Effective operation enablement **MUST** be computed at compile/startup time.
- Disabled operations **MUST NOT** register routes/handlers in generated output.

## 7. Security, CORS, and Secret Redaction

`security` schema:

| Field | Type | Required | Default |
|---|---|---:|---|
| `cors.allowedOrigins` | array<string> | NO | `[]` |
| `cors.allowCredentials` | boolean | NO | `false` |
| `cors.allowedMethods` | array<string> | NO | implementation default |
| `headers.enableStandard` | boolean | NO | `true` |
| `redaction.enabled` | boolean | NO | `true` |
| `redaction.keys` | array<string> | NO | see below |

Rules:

- If `allowCredentials: true`, wildcard origin (`*`) **MUST NOT** be accepted.
- Standard security headers **SHOULD** be emitted when `headers.enableStandard` is true.
- Redaction **MUST** apply to logs, errors, diagnostics, and debug dumps.
- Default redacted key set **SHOULD** include case-insensitive matches for: `password`, `secret`, `token`, `apiKey`, `authorization`, `cookie`.
- Interpolated secret values **MUST NOT** be emitted in plaintext in any engine logs.

## 8. Access Rule Schema (Pipeline-Compatible)

Access rules are declarative and compile into ordered evaluation steps.

### 8.1 Collection Access Shape

`collections.<name>.access`:

| Field | Type | Required | Description |
|---|---|---:|---|
| `list` | `AccessOperationConfig` | NO | Access policy for list operation. |
| `get` | `AccessOperationConfig` | NO | Access policy for get-by-id. |
| `create` | `AccessOperationConfig` | NO | Access policy for create. |
| `update` | `AccessOperationConfig` | NO | Access policy for partial update. |
| `replace` | `AccessOperationConfig` | NO | Access policy for full replace. |
| `delete` | `AccessOperationConfig` | NO | Access policy for delete. |

Shorthand values are also valid for each operation key:

- `public`: operation is publicly accessible.
- `"*"`: operation requires a resolved identity.
- `<collection>:*`: operation requires identity from a specific auth collection.
- Rule array (`array<AccessRule>`): advanced allow rules.

### 8.2 AccessRule

| Field | Type | Required | Default | Notes |
|---|---|---:|---|---|
| `principal` | string | YES | - | Who the rule applies to. |
| `when` | string (expression) | NO | `true` | Condition over context/document/input. |
| `filter` | string (expression) | NO | none | Row-level constraint for read/list/update/delete. |
| `writeFields` | array<string> | NO | `[]` | Allowed writable fields. |
| `reason` | string | NO | none | Optional diagnostics label. |

`principal` supports:

- `public`
- `"*"`
- `users:*`

Compilation semantics:

- Rules **MUST** be evaluated in declaration order.
- Engine **MUST** support first-match mode in v0.1 (configurable later).
- Expressions **MUST** compile to an internal AST/pipeline step at startup.
- Expression context **MUST** support `currentIdentity`, `document`, `input`, and provider passthrough claims when present.

## 9. Validation and Error Semantics

### 9.1 Validation Phases

Implementations **MUST** validate in this order:

1. YAML parse and type-shape checks.
2. Interpolation resolution and missing-variable checks.
3. Schema validation (required fields, type compatibility, enum constraints).
4. Cross-reference validation (collections, fields, auth refs, access principals).
5. Compilation validation (expression parse/compile, operation graph consistency).

### 9.2 Error Contract

- Startup/build validation failures **MUST** prevent serving traffic.
- Each error **MUST** include: `code`, `message`, and `path` (YAML pointer-like path).
- Errors **SHOULD** include `hint` when an actionable fix is obvious.
- Multiple independent errors **SHOULD** be aggregated in one report when safe.
- Warnings **MUST NOT** block startup unless strict mode is enabled.

Recommended error shape:

```yaml
code: SCHEMA_INVALID_TYPE
message: "Field type mismatch: expected number"
path: "collections.posts.fields.views.default"
hint: "Set default to a numeric literal"
```

## 10. Complete Example (v0.1)

```yaml
version: "0.1"

api:
  basePath: "/api"
  version: "v1"
  pagination:
    defaultPageSize: 20
    maxPageSize: 100
  operations:
    defaults:
      list: true
      get: true
      create: true
      update: true
      replace: true
      delete: true

security:
  cors:
    allowedOrigins:
      - "https://app.example.com"
      - "${CORS_ORIGIN:-http://localhost:5173}"
    allowCredentials: true
    allowedMethods: ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]
  headers:
    enableStandard: true
  redaction:
    enabled: true
    keys: ["password", "token", "apiKey", "authorization", "cookie", "secret"]

collections:
  users:
    type: auth
    auth:
      identifier: email
      via: [password]
    fields:
      email:
        type: string
        required: true
        unique: true
        format: email
      passwordHash:
        type: string
        required: true
      displayName:
        type: string
        required: true
        minLength: 2
        maxLength: 120
      role:
        type: enum
        values: ["user", "admin"]
        default: "user"
      createdAt:
        type: datetime
      metadata:
        type: object
        additionalProperties: true
    operations:
      delete: false
    access:
      list:
        - effect: deny
          principal: { type: public }
      get:
        - effect: allow
          principal: { type: identity, collection: users }
          when: "document._id == currentIdentity._id or currentIdentity.role == 'admin'"
      update:
        - effect: allow
          principal: { type: identity, collection: users }
          when: "document._id == currentIdentity._id"
          writeFields: ["displayName", "metadata"]
      create:
        - effect: deny
          principal: { type: public }

  posts:
    type: base
    fields:
      title:
        type: string
        required: true
        minLength: 3
        maxLength: 160
      body:
        type: string
        required: true
      authorId:
        type: ref
        ref: users
        required: true
        store: id
        expand:
          allowed: true
          fields: ["_id", "displayName"]
          maxDepth: 1
      tags:
        type: array
        items:
          type: string
      published:
        type: boolean
        default: false
      createdAt:
        type: datetime
    softDelete: true
    access:
      list:
        - effect: allow
          principal: { type: public }
          filter: "document.published == true"
        - effect: allow
          principal: { type: identity, collection: users }
          filter: "document.authorId == currentIdentity._id"
      create:
        - effect: allow
          principal: { type: authenticated }
      update:
        - effect: allow
          principal: { type: identity, collection: users }
          when: "document.authorId == currentIdentity._id"
          writeFields: ["title", "body", "tags", "published"]
      delete:
        - effect: allow
          principal: { type: identity, collection: users }
          when: "document.authorId == currentIdentity._id or currentIdentity.role == 'admin'"

options:
  strict: false
```

## 11. Conformance Notes

- Engines claiming v0.1 conformance **MUST** implement required fields and rules in this document.
- Engines **MAY** add extension fields under namespaced keys (recommended prefix: `x-`).
- Extension fields **MUST NOT** alter required v0.1 semantics unless explicitly marked as non-conformant mode.
