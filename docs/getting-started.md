---
title: Getting Started
---

# Getting Started

## Prerequisites

- Python 3.11 or later
- MongoDB 6+ (via Docker: `docker-compose up` in the repo root, or install locally)
- pip

## Installation

```bash
pip install yaml-api-generator
```

Or from source:

```bash
git clone https://github.com/sebastiaoteixeira/yaml-framework.git
cd yaml-framework
pip install -e .
```

## First run

1. Create a file called `myapp.yaml`:

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

2. Start MongoDB:

A `docker-compose.yml` is included in the project root. No extra setup needed.

```bash
docker-compose up -d
```

Or ensure MongoDB is running on `localhost:27017`.

3. Run the server:

```bash
yaml-api dev myapp.yaml
```

4. Open http://localhost:8000/docs to see the generated API in Swagger UI.

5. Test with curl:

```bash
curl http://localhost:8000/api/v1/notes
```

Expected output:

```json
[]
```

An empty list means the server is running and connected to MongoDB. There are no notes yet.

## Project structure

```text
myproject/
  myapp.yaml          # your spec file
  myapp/              # custom handlers (only if using custom operations)
    __init__.py
    handlers/
      __init__.py
      notes.py        # handler functions
```

## What gets generated (compile mode)

```bash
yaml-api compile myapp.yaml --output ./target
```

Produces:

```text
target/
  app.py              # FastAPI application entry point
  dependencies/       # auth, JWT, MongoDB connection
  routes/             # generated route files per collection
  repositories/       # MongoDB repository implementations
  models/             # Pydantic models
```

## Next steps

Continue to the [Tutorial](./Tutorial/01-hello-world.md) to build a complete API step by step, or read the [Concepts](./concepts.md) page for an architecture overview.
