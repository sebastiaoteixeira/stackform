---
title: "Reference: `yaml-api dev`"
description: Starts a live FastAPI development server directly from a YAML spec. No compilation step required.
---

# Reference: `yaml-api dev`

Starts a live FastAPI development server directly from a YAML spec. No compilation step required.

## Usage

```bash
yaml-api dev <file.yaml> [options]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `<file.yaml>` | Path to the YAML spec file. Required. |

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Host address to bind to. Use `0.0.0.0` to expose on all interfaces. |
| `--port` | `8000` | TCP port to listen on. |
| `--schema` | auto-detected | Path to a custom JSON Schema for spec validation. Auto-detected from `version:` if omitted. |

## Examples

```bash
# Start on default host/port
yaml-api dev myapp.yaml

# Expose on all interfaces, port 3000
yaml-api dev myapp.yaml --host 0.0.0.0 --port 3000

# Use a custom schema for validation
yaml-api dev myapp.yaml --schema ./custom-schema.json
```

## Auto-generated docs

When the server is running, interactive API documentation is available at:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## Environment variables

`${VAR}` interpolations in the spec are resolved from environment variables at startup:

```bash
export MONGO_URI=mongodb://localhost:27017
export MONGO_DB=myapp
yaml-api dev myapp.yaml
```

Missing required variables (without `:-` fallback) cause an immediate startup error with the variable name and spec path.

## Starting MongoDB

The dev server requires a running MongoDB instance. Start one with Docker:

```bash
docker-compose up -d
```

Or use the connection string for a remote MongoDB (Atlas, etc.) via `${MONGO_URI}`.
