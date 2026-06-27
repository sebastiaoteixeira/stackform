---
title: Getting Started
description: Install the generator, write your first v0.2 spec, run it, and build a project from it.
---

## Prerequisites

- Python 3.11 or later
- MongoDB 6+ (via Docker, or installed locally)
- pip

## Installation

Install from source:

```bash
git clone https://github.com/sebastiaoteixeira/yaml-framework.git
cd yaml-framework
pip install -e .
```

A published package (`pip install yaml-api-generator`) will be available once released; until then use the source install above.

## First run

1. Create a file called `myapp.yaml`:

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

mongo:
  uri: mongodb://localhost:27017
  database: myapp

entities:
  note:
    fields:
      id: { type: id }
      title: { type: string, required: true }
      body: { type: string }

repositories:
  notes:
    entity: note

services:
  notes:
    repository: notes

controllers:
  notes:
    service: notes
    base_path: /notes
    access: public
```

A few things to know about this spec:

- `version: "0.2"` is required. If you omit it the file is parsed as a v0.1 spec, which uses a different schema.
- Every entity needs exactly one `type: id` field (or a natural-key `pk:`). Declaring zero raises `ID_FIELD_MISSING`; the `id` value is server-generated (uuidv7) on create.
- The `api:` block fixes the URL prefix. With `basePath: /api` and `version: v1`, the notes routes live under `/api/v1/notes`. If you omit `version`, there is no version segment and the routes are `/api/notes`. Showing the `api:` block keeps the URLs in this guide reproducible.
- A repository exposes all six CRUD operations by default (list, get, create, update, replace, delete). Restrict the set with `repositories.notes.crud: [list, get]`.

2. Start MongoDB:

The development server reads `YAML_API_MONGO_URI` / `YAML_API_MONGO_DB` (defaulting to `mongodb://localhost:27017` and `yaml_api`), so make sure Mongo is reachable. The quickest way is Docker:

```bash
docker run -d -p 27017:27017 --name mongo mongo:8
```

Or ensure a local MongoDB is running on `localhost:27017`.

3. Run the server:

```bash
yaml-api run myapp.yaml
```

`run` serves the app in-process; it binds `127.0.0.1:8000` by default. Use `--host 0.0.0.0` and `-p`/`--port` to change that, `--raw` to use the raw ASGI runner, and `--json` for machine-readable errors. Pass `-r`/`--reload` to rebuild the app automatically when the spec changes; otherwise restart it to pick up edits.

4. Open http://127.0.0.1:8000/docs to see the generated API in Swagger UI.

5. Test with curl:

```bash
curl http://127.0.0.1:8000/api/v1/notes
```

Expected output:

```json
[]
```

An empty list means the server is running and connected to MongoDB. There are no notes yet.

## Secure by default

As soon as your spec declares a `type: auth` entity, every non-public route requires a valid principal; a route is open only when its controller sets `access: public`. The `notes` controller above is explicitly public, so anyone can call it. See [Authentication required by default](./Reference/auth/auth-required-by-default.md) for the full rule.

## Building a project

`run` is for local development. To emit a standalone project you can deploy, use `build`:

```bash
yaml-api build myapp.yaml -o ./target
```

The positional argument after the file selects what to build: `all` (default), `backend`, `frontend`, or `deploy`. Pick the backend framework with `-t`/`--target` (`fastapi` (default), `drf`, or `raw`); choose the output directory with `-o`/`--output` (default `./target`); supply an external JSON schema with `-s`/`--schema`; add `--json` for machine-readable errors.

The backend lands in `target/backend/`:

```text
target/
  backend/
    app.py            # FastAPI application entry point
    dependencies/     # MongoDB connection, auth, JWT, authorization
    routes/           # generated route files per collection
    repositories/     # MongoDB repository implementations
    services/         # per-operation service layer
    models/           # Pydantic models
    requirements.txt
```

A `frontend/` directory is generated only when the spec contains a `ui:` block (it goes in `target/frontend/` for an `all`/`frontend` build). Likewise, deploy artifacts are produced only when a `deploy:` block is present.

## Custom handlers

Custom operations reference your own code by dotted import path (for example `myapp.handlers.notes.publish`), resolved against your Python path; there is no fixed handler directory layout. See [Custom operations](./Tutorial/09-custom-operations.md) for the handler contract.

## Next steps

Continue to the [Tutorial](./Tutorial/01-hello-world.md) to build a complete API step by step, or read the [Concepts](./concepts.md) page for an architecture overview.
