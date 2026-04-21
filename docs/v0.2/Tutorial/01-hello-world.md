---
title: "Tutorial 01: Hello World"
description: Minimal spec -- one entity, one repository, one controller with public access.
---

**Concept introduced:** Minimal spec -- one entity, one repository, one controller with public access.

**Prerequisites:** Complete the [Getting Started](../../getting-started.md) guide first. You need `yaml-api-generator` installed and MongoDB running.

## The spec

```yaml
version: "0.2"

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
  notes: {}

controllers:
  notes:
    service: notes
    base_path: /notes
    access: public
```

## What this generates

| Method | Path | Description |
|--------|------|-------------|
| GET | /notes | List all notes |
| GET | /notes/{id} | Get a note by ID |
| POST | /notes | Create a note |
| PATCH | /notes/{id} | Update a note (partial) |
| DELETE | /notes/{id} | Delete a note |

`replace` (PUT) is disabled by default.

## Run it

```bash
yaml-api dev myapp.yaml
```

The server starts at `http://127.0.0.1:8000`. Interactive docs are at `/docs`.

## Create a note

```bash
curl -X POST http://127.0.0.1:8000/notes \
  -H 'Content-Type: application/json' \
  -d '{"title": "First note", "body": "Hello from yaml-api-generator"}'
```

The `id` field is auto-generated (uuidv7). You never send it in the request body.

**Note:** If you omit the `id` field declaration entirely, the engine adds an implicit `id: { type: id }` with `format: uuidv7` automatically. Declaring it explicitly is optional but recommended for clarity.

## Key points

- `entities:` defines data shapes. `repositories:` binds an entity to storage. `controllers:` defines HTTP routes.
- `access: public` at the controller level means all operations on this controller require no authentication.
- The `services:` section is a thin wiring layer between controllers and repositories. An empty `{}` value means use all default operations from the bound repository.

