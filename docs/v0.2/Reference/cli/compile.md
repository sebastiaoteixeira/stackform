---
title: "Reference: `yaml-api compile`"
description: Compiles a YAML spec into a standalone project (FastAPI, Django REST Framework, or raw IR).
---

Compiles a YAML spec into a standalone project (FastAPI, Django REST Framework, or raw IR).

## Usage

```bash
yaml-api compile <file.yaml> [options]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `<file.yaml>` | Path to the YAML spec file. Required. |

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--target` | `fastapi` | Output framework. Values: `fastapi`, `drf`, `raw`. |
| `--output` | `./target` | Output directory for generated project files. |
| `--schema` | auto-detected | Path to a custom JSON Schema for spec validation. Auto-detected from `version:` if omitted. |

## Targets

### `fastapi`

Generates a standalone FastAPI project with:
- `app.py` — FastAPI application
- `routes/` — route handlers
- `models/` — Pydantic models
- `repositories/` — MongoDB repository implementations
- `services/` — service layer
- `dependencies/` — auth and DB dependency injection

### `drf`

Generates a Django REST Framework project with:
- `project/` — Django settings, URLs, WSGI/ASGI
- `api/` — serializers, views, repositories, authentication
- `requirements.txt`

### `raw`

Outputs the parsed Intermediate Representation as JSON. Useful for debugging the parser or building custom code generators.

## Examples

```bash
# Compile to FastAPI in ./target (default)
yaml-api compile myapp.yaml

# Compile to DRF in a custom output directory
yaml-api compile myapp.yaml --target drf --output ./my-django-api

# Compile with a custom schema file
yaml-api compile myapp.yaml --schema ./my-schema.json

# Generate raw IR
yaml-api compile myapp.yaml --target raw --output ./ir.json
```

## Environment variables

`${VAR}` interpolations in the spec are resolved from environment variables at compile time. Set required variables before running:

```bash
export MONGO_URI=mongodb://localhost:27017
export MONGO_DB=myapp
yaml-api compile myapp.yaml
```
