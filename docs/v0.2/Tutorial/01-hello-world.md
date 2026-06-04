---
title: "Tutorial 01: Hello World"
description: Minimal spec -- one entity, one repository, one controller with public access.
---

**Concept introduced:** Minimal spec -- one entity, one repository, one controller with public access.

**Prerequisites:** Complete the [Getting Started](../getting-started.md) guide first. You need `yaml-api-generator` installed and MongoDB running.

## The spec

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1

mongo:
  uri: mongodb://localhost:27017
  database: yaml_api

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
  notes: {}

controllers:
  notes:
    service: notes
    base_path: /notes
    access: public
```

The `api:` block sets where routes live. With `basePath: /api` and `version: v1`,
every route is prefixed with `/api/v1`. Omit `version` and the segment disappears
(routes become `/api/...`); omit the whole `api:` block and `basePath` defaults to
`/api` with no version.

## What this generates

Routes are composed as `basePath + version + base_path + suffix`, so the
controller's `base_path: /notes` lands under `/api/v1/notes`.

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/v1/notes | List all notes |
| GET | /api/v1/notes/{id} | Get a note by ID |
| POST | /api/v1/notes | Create a note |
| PATCH | /api/v1/notes/{id} | Update a note (partial) |
| PUT | /api/v1/notes/{id} | Replace a note (full) |
| DELETE | /api/v1/notes/{id} | Delete a note |

All six CRUD operations are enabled by default. To expose only a subset, list the
operations you want under the repository's `crud:` field, for example
`repositories.notes.crud: [list, get]` for a read-only resource. An operation you
leave out produces no route, no handler, and no UI affordance.

## Run it

```bash
yaml-api run myapp.yaml
```

The server starts at `http://127.0.0.1:8000` (override with `--host` and
`-p/--port`). Interactive docs are at `/docs`. The `run` server reads the database
from `YAML_API_MONGO_URI` / `YAML_API_MONGO_DB` if you need to point it elsewhere;
restart it to pick up spec changes.

## Create a note

```bash
curl -X POST http://127.0.0.1:8000/api/v1/notes \
  -H 'Content-Type: application/json' \
  -d '{"title": "First note", "body": "Hello from yaml-api-generator"}'
```

The `id` field is server-generated (uuidv7 by default). You never send it in the
request body.

**Note:** Every entity must declare exactly one field of `type: id`. If none is
present, generation fails with `ID_FIELD_MISSING`; if more than one is present, it
fails with `ID_FIELD_MULTIPLE`. There is no implicit `id` injection. The id format
defaults to `uuidv7`; set `format: uuidv4` on the field to switch.

## Key points

- `entities:` defines data shapes. `repositories:` binds an entity to storage (the
  repository name is also the MongoDB collection name). `controllers:` defines HTTP
  routes.
- `access: public` at the controller level means every operation on this controller
  is reachable without authentication.
- The `services:` section is a thin wiring layer between controllers and
  repositories. An empty `{}` value enables all CRUD operations the bound repository
  exposes (all six unless the repository narrows them with `crud:`).
