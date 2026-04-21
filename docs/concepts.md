# Concepts

This page explains the architecture of yaml-api-generator for beginners.

## The YAML spec

Your spec is the single source of truth. It declares entities (data models), repositories (storage), services (business logic), and controllers (HTTP routes). Everything the engine needs to generate your API is in this one file.

## The data flow

```text
YAML Spec
  |
  v
[Entity] --> fields, types, validation
  |
  v
[Repository] --> MongoDB collection, CRUD operations
  |
  v
[Service] --> business logic layer (pass-through by default)
  |
  v
[Controller] --> HTTP routes, access control, base path
  |
  v
FastAPI Server --> GET /api/v1/notes, POST /api/v1/notes, etc.
```

## Why four layers?

- **Entity** = what your data looks like. Fields, types, and validation rules. Shared across repos, services, and controllers.
- **Repository** = where and how data is stored. Maps an entity to a MongoDB collection and defines which CRUD operations exist. Could be swapped without changing the API surface.
- **Service** = what operations are available. By default, services pass through to repositories. Custom logic (like a "publish" action) goes here.
- **Controller** = how operations are exposed over HTTP. Sets the base path, HTTP methods, and access rules. This is where authorization is declared.

## Authentication flow

1. User registers via `POST /users/register`. The password is hashed and stored in the `_auth` namespace in MongoDB.
2. User logs in via `POST /users/login`. The server returns a JWT token.
3. Subsequent requests include the JWT in the `Authorization: Bearer <token>` header.
4. The server decodes the JWT, resolves the principal (identity + roles).
5. Access rules on the controller are checked against the principal. The request is allowed or denied.

## Glossary

- **Principal** -- The authenticated identity making a request. Contains the user's ID (`sub`), their database record, and their roles.
- **JWT** -- JSON Web Token. A signed string that encodes a user's identity so the server can authenticate requests without a database lookup on every call.
- **Repository** -- The data access layer that maps an entity to a MongoDB collection and provides CRUD operations.
- **Service** -- The business logic layer between controllers and repositories. By default it passes through to the repository; custom handlers go here.
- **Controller** -- The HTTP layer that exposes service operations as routes, sets base paths, and declares access rules.
- **Pipeline** -- An ordered sequence of steps that processes each incoming request (authentication, authorization, then the repository operation).
- **Step** -- A single unit of work in a pipeline, such as resolving the principal, checking access rules, or executing a database operation.

## Next steps

Start building with the [Tutorial](./Tutorial/01-hello-world.md), or jump to the [Reference](./Reference/) for detailed spec documentation.
