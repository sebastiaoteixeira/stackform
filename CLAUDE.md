# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YAML-API-Generator is a YAML-driven REST API engine that generates fully functional CRUD APIs backed by MongoDB. It reads a declarative YAML specification and spawns a FastAPI server with authentication, authorization, and data validation — zero hand-written server code required.

## Commands

```bash
# Install in development mode
pip install -e .

# Run the server
yaml-api-serve <yaml_file> [--schema <schema_file>] [--host 127.0.0.1] [--port 8000]

# Start MongoDB locally
docker-compose up

# Lint
ruff check src/
```

No test suite exists yet.

## Architecture

**Data flow:** YAML → Parser → JSON Schema Validator → IR (Intermediate Representation) → PipelineBuilder → FastAPI routes → Runtime

### Key Modules (`src/yaml_api_generator/`)

- **`server.py`** — CLI entry point (`yaml-api-serve`). Parses args, builds the FastAPI app, connects to MongoDB, starts Uvicorn.
- **`parser.py`** — YAML loading, `${ENV}` interpolation, JSON Schema validation, IR generation. Main entry: `load_and_generate_ir()`.
- **`ir.py`** — Frozen dataclasses defining the Intermediate Representation: `IRDocument`, `IRCollection`, `IRRoute`, `IRIdentityCollection`, `IROperations`.
- **`fastapi_factory.py`** — Dynamically creates Pydantic models and registers FastAPI routes. `create_pydantic_model()` builds request validators per collection/operation.
- **`pipeline.py`** — Step execution engine. `Pipeline.run()` executes an ordered list of steps, passing a `RequestContext` through them.
- **`pipeline_builder.py`** — Assembles the correct step sequence per route (auth → authz → repository).
- **`context.py`** — `RequestContext` dataclass carrying request metadata through the pipeline.

### Steps (`steps/`)

Steps are the units of work in a pipeline:

- **`authentication.py`** — `ResolvePrincipalStep`: extracts credentials (Basic auth or Bearer/X-API-Key), validates against DB, resolves principal `{sub, identity_collection, record, roles}`.
- **`authorization.py`** — `AuthorizeRouteStep` (401/403 enforcement), `ValidateIdentityCreateStep` (auth field validation on signup).
- **`repositories.py`** — CRUD steps (`RepositoryListStep`, `RepositoryGetStep`, `RepositoryCreateStep`, `RepositoryUpdateStep`, `RepositoryReplaceStep`, `RepositoryDeleteStep`). Handle ID generation (uuidv7/v4), password hashing, field normalization.

### Repository Layer (`repositories/`)

- **`base.py`** — `BaseRepository` ABC with `list`, `get`, `create`, `update`, `replace`, `delete`.
- **`mongodb.py`** — `MongoRepository` implementation. Normalizes MongoDB `_id` ↔ YAML-defined ID field. Filters `password`/`passwordHash` from responses.

### Auth (`auth/`)

- **`password.py`** — PBKDF2-SHA256 hashing (390k rounds) via `hash_password()` / `verify_password()`.

## Tech Stack

- **Python** ≥3.11
- **FastAPI** + **Uvicorn** (ASGI)
- **Pydantic v2** (dynamic model generation)
- **PyYAML** + **jsonschema** (YAML parsing and Draft 2020-12 validation)
- **pymongo** with `AsyncMongoClient` (MongoDB driver)
- **MongoDB 8** (via Docker Compose)

## YAML Spec

The YAML specification (v0.1) is documented in `YAML-Specification-v0.1.md` with JSON Schema at `yaml-spec-v0.1.schema.json` (also bundled at `src/yaml_api_generator/schemas/`). Example configs live in `examples/`.

Key concepts: collections with typed fields (id, string, number, boolean, datetime, enum, array, object, ref), auth collections (`type: auth` with password/apiKey), access rules (public/authenticated/identity-based), and `${ENV:-default}` interpolation.

## Pydantic Model Naming

Dynamically generated models follow: `{CollectionCapitalized}{OperationCapitalized}Payload` (e.g., `UsersCreatePayload`). Updates make all fields optional.

## Error Handling

Parser errors use structured JSON with `code`, `message`, `path`, `hint`. Error codes include `YAML_PARSE_ERROR`, `INTERPOLATION_MISSING_VAR`, `ID_FIELD_MISSING`, `AUTH_PASSWORD_FIELD_FORBIDDEN`, `SCHEMA_VALIDATION_ERROR`, etc.

## v0.2 Design Decisions

### 1. Entity extends + abstract
Entities can use `extends: parent` to inherit fields, type, and auth from another entity. `abstract: true` marks entities that are templates only — they're stripped after desugaring and can't be referenced by repositories.

### 2. Operations moved to repositories
`operations` no longer live on entities. They belong on repositories (storage/behavior concern, not data shape concern).

### 3. Identity refs use entity names
`identity:user` (not `identity:users`). Entity name is the stable identifier. Repository key is an implementation detail irrelevant to authorization.

### 4. Unified access syntax replacing `authenticated`
- `public` — no auth
- `*` — any authenticated principal (replaces `authenticated`)
- `user:*` — any authenticated user entity
- `user:admin` — user with admin role
- `[user:admin, user:moderator]` — multiple roles
- `[user:*, apiClient:*]` — multiple entity types
- With single auth entity, entity prefix can be omitted: `admin` instead of `user:admin`

### 5. Roles are per-entity, not global
Each auth entity declares its own roles via `auth.roles: fieldName` pointing to an enum field. Different entities have different role semantics.

### 6. Role hierarchy/composition in separate top-level `roles` section
- Entity declares `auth.roles: role` (just the field)
- Enum field declares valid values
- Top-level `roles:` section declares composition/hierarchy relationships only (not permissions)
```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
```
- admin includes moderator, moderator includes user
- `access: user:moderator` matches admin too

### 7. Access control stays on controllers
No permission maps at entity or top level. Controllers declare access rules close to the resource. Principle of least privilege.

### 8. Internal attribute namespacing
Implicit fields (passwordHash, etc.) stored under `_auth` namespace in MongoDB instead of flat top-level fields. `principal.record` returns clean user fields.

### 9. Multiple auth entities — scoped roles
- Single auth entity: unscoped `<role>` is allowed (`admin`, `moderator`). The entity is inferred.
- Multiple auth entities: `<entity>:<role>` is **required** (`user:admin`, `apiClient:enterprise`). Unscoped `<role>` is a validation error when multiple auth entities exist.

### 10. Primary keys — `type: id` + optional `pk`
- `type: id` stays as-is: auto-generated UUID, implicitly the PK. `format: uuidv7` (default) or `format: uuidv4`.
- If no `id` field declared, an implicit one is added (auto-generated uuidv7).
- `pk: fieldname` at entity level for natural keys (e.g., ISO codes). The referenced field can be any type. No auto-generated `id` is added when `pk` is declared.

## v0.2 Examples

### Entity inheritance and abstract entities
```yaml
entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }
      updatedAt: { type: datetime }

  user:
    extends: base
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  post:
    extends: base
    fields:
      title: { type: string, required: true }
      content: { type: string }
      authorId: { type: ref, ref: user }
      published: { type: boolean, default: false }

  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string }
```

### UUID versions
```yaml
fields:
  id: { type: id }                   # uuidv7 (default)
  id: { type: id, format: uuidv4 }   # explicit uuidv4
  id: { type: id, format: uuidv7 }   # explicit uuidv7
```

### Natural keys via `pk`
```yaml
entities:
  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string }
  currency:
    pk: iso
    fields:
      iso: { type: string }
      name: { type: string }
      symbol: { type: string }
```

### Operations on repositories (not entities)
```yaml
repositories:
  users:
    entity: user
  posts:
    entity: post
    operations:
      replace: true
  countries:
    entity: country
```

### Role hierarchy (top-level, separate from entities)
```yaml
roles:
  user:
    admin: [moderator]
    moderator: [user]
```

### Unified access syntax — single auth entity (prefix optional)
```yaml
controllers:
  posts:
    service: posts
    base_path: /posts
    access: public
    operations:
      create: { access: "*" }
      update: { access: moderator }
      delete:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
```

### Unified access syntax — multiple auth entities (prefix required)
```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      role: { type: enum, values: [admin, moderator, user] }
  apiClient:
    type: auth
    auth:
      identifier: clientId
      via: apiKey
      roles: tier
    fields:
      tier: { type: enum, values: [free, premium, enterprise] }

roles:
  user:
    admin: [moderator]
    moderator: [user]
  apiClient:
    enterprise: [premium]
    premium: [free]

controllers:
  posts:
    operations:
      delete:
        access:
          - user:moderator
          - apiClient:enterprise
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId
```

### Internal attribute namespacing (MongoDB storage)
```
# Before (flat):
{ "id": "abc", "email": "foo@bar.com", "passwordHash": "pbkdf2:..." }

# After (namespaced):
{ "id": "abc", "email": "foo@bar.com", "_auth": { "passwordHash": "pbkdf2:..." } }
```

### Full minified example
```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  operations:
    defaults:
      list: true
      get: true
      create: true
      update: true
      replace: false
      delete: true
    auth:
      register: true
      login: true

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  user:
    extends: base
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }
      role:
        type: enum
        values: [admin, moderator, user]
        default: user

  post:
    extends: base
    fields:
      title: { type: string, required: true }
      content: { type: string }
      authorId: { type: ref, ref: user }
      published: { type: boolean, default: false }

  country:
    pk: code
    fields:
      code: { type: string }
      name: { type: string }

roles:
  user:
    admin: [moderator]
    moderator: [user]

repositories:
  users:
    entity: user
  posts:
    entity: post
    operations:
      replace: true
  countries:
    entity: country

services:
  users:
    repository: users
  posts:
    repository: posts
    operations:
      publish: { handler: posts.publish }
  countries:
    repository: countries

controllers:
  users:
    service: users
    base_path: /users
    access: "*"
    operations:
      register: { access: public }
      login: { access: public }
      delete:
        access:
          - given:
              principal: identity:user
            when: principal.sub equals document.id

  posts:
    service: posts
    base_path: /posts
    access: public
    operations:
      create: { access: "*" }
      update:
        access:
          - admin
          - given:
              principal: identity:user
              document: posts
            when: principal.sub not equals document.authorId
            then: deny
          - then: allow
      replace: { access: "*" }
      publish: { method: POST, path: "/{id}/publish", access: "*" }
      delete:
        access:
          - moderator
          - given:
              principal: identity:user
              document: posts
            when: principal.sub equals document.authorId

  countries:
    service: countries
    base_path: /countries
    access: public
    operations:
      create: { access: admin }
      update: { access: admin }
      delete: { access: admin }
```
