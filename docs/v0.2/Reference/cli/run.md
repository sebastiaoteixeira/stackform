---
title: "`stackform run`"
description: Serves an application directly from a YAML spec, with no build step. The server is rebuilt from the spec on each start.
---

Serves an application directly from a YAML spec, with no build step. This is the fastest way to try a spec: it parses, validates, and serves in one command.

By default the app is assembled from the spec once, when the process starts. Pass `-r`/`--reload` to watch the spec and rebuild the app whenever the YAML file changes; otherwise, restart the command to pick up edits.

## Usage

```bash
stackform run <file.yaml> [options]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `<file.yaml>` | Path to the YAML spec file. Required; must exist. |

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Host address to bind. Use `0.0.0.0` to expose on all interfaces. |
| `-p`, `--port` | `8000` | TCP port to listen on. |
| `-r`, `--reload` | off | Watch the spec and rebuild the running app whenever it changes. |
| `--raw` | off | Serve the raw-ASGI app instead of the FastAPI app. |
| `-s`, `--schema` | auto-detected | Path to a JSON Schema for spec validation. The dialect is otherwise chosen from the spec's `version:` field. |
| `--json` | off | Emit validation errors as JSON instead of human-readable text. |

The host and port come from `--host` and `-p`/`--port` only; they are not read from environment variables.

## Examples

```bash
# Start on the default host/port (127.0.0.1:8000)
stackform run myapp.yaml

# Expose on all interfaces, port 3000
stackform run myapp.yaml --host 0.0.0.0 -p 3000

# Reload the app whenever the spec changes
stackform run myapp.yaml --reload

# Serve the raw-ASGI variant
stackform run myapp.yaml --raw

# Validate against an explicit schema, JSON error output
stackform run myapp.yaml -s ./custom-schema.json --json
```

## Auto-generated docs

Once the server is up, interactive API documentation is served at:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## Environment variables

The dev server reads its MongoDB connection from environment variables, falling back to the spec's `mongo:` block:

| Variable | Default | Description |
|----------|---------|-------------|
| `YAML_API_MONGO_URI` | `mongo.uri` from the spec | MongoDB connection string for the dev server. |
| `YAML_API_MONGO_DB` | `mongo.database` from the spec | MongoDB database name for the dev server. |

These are specific to `stackform run`. A built backend produced by `stackform build` reads `MONGO_URI` / `MONGO_DB` instead -- see [Environment variables](../configuration/environment-variables.md).

Authentication is configured through the same variables the built backend uses:

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | dev placeholder | Secret used to sign and verify JWTs. Set a real value before exposing the server. |
| `JWT_EXPIRATION_HOURS` | `24` | Token lifetime in hours. |
| `PASSWORD_HASH_ROUNDS` | `390000` | PBKDF2 iteration count for password hashing. |

`${VAR}` interpolations in the spec are resolved from the environment at startup, after the YAML is loaded and before schema validation. A missing variable without a `:-default` fallback aborts startup (exit 1) with `Environment variable 'X' is required`.

Password routes have the same path in development-server and generated
FastAPI modes. For an auth collection named `users` with
`api: { basePath: /api, version: v1 }`, both expose
`POST /api/v1/users/login`. See the runnable SQLite example at
`examples/v03/password-role/spec.yaml`.

```bash
export YAML_API_MONGO_URI=mongodb://localhost:27017
export YAML_API_MONGO_DB=myapp
export JWT_SECRET=change-me
stackform run myapp.yaml
```

## Starting MongoDB

A spec using MongoDB needs a reachable MongoDB instance; the dev server does not start one for you. SQL specs, including the password/role example, do not require MongoDB. Run MongoDB locally when the selected spec needs it, for example:

```bash
docker run -d -p 27017:27017 mongo:8
```

Or point `YAML_API_MONGO_URI` at a managed instance (Atlas, etc.). If MongoDB is unreachable, requests that touch the database fail with a `ServerSelectionTimeoutError`.
