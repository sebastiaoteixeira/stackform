---
title: "`stackform build`"
description: Builds a standalone project from a YAML spec -- backend (FastAPI, DRF, or raw ASGI), React frontend, deployment artifacts, or all three.
---

Builds a standalone project from a YAML spec. A single invocation can produce the backend, the React frontend, the deployment artifacts, or all three at once.

## Usage

```bash
stackform build <file.yaml> [all|backend|frontend|deploy] [options]
```

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `<file.yaml>` | -- | Path to the YAML spec file. Required; must exist. |
| `[what]` | `all` | What to build: `all`, `backend`, `frontend`, or `deploy`. |

The `[what]` positional selects which outputs to generate:

- `all` builds the backend, and additionally the frontend if the spec has a `ui:` block and the deploy artifacts if it has a `deploy:` block. Missing optional blocks are skipped silently.
- `backend` builds only the backend.
- `frontend` builds only the frontend. Fails if there is no `ui:` block, or if `ui.frontend.pack` is unset.
- `deploy` builds only the deployment artifacts. Fails if there is no `deploy:` block.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `-t`, `--target` | `fastapi` | Backend framework: `fastapi`, `drf`, or `raw`. |
| `-o`, `--output` | contextual | Output directory. Defaults to `./target`; a frontend-only build uses `ui.frontend.output` or `./frontend`. |
| `-s`, `--schema` | auto-detected | Path to a JSON Schema for spec validation. The dialect is otherwise chosen from the spec's `version:` field. |
| `--json` | off | Emit validation/build errors as JSON instead of human-readable text. |

## Output structure

Where files land depends on the `[what]` positional:

- `backend` (and the backend part of `all`) is written to `<output>/backend`.
- `frontend` as part of `all` is written to `<output>/frontend`.
- `frontend` built on its own writes to `-o`, then `ui.frontend.output`, then `./frontend` in precedence order.
- `deploy` artifacts are written directly into `<output>` (no nested subdirectory).

## Backend targets

### `fastapi`

The default. Generates a standalone FastAPI project under `<output>/backend`:

- `app.py` -- the ASGI application
- `routes/` -- route handlers
- `models/` -- Pydantic models
- `repositories/` -- datastore-specific MongoDB or SQL repository implementations
- `services/` -- service layer
- `dependencies/` -- auth and database dependency injection
- `.env` -- runtime settings with real values (secret-typed settings such as `JWT_SECRET` and each `<PROVIDER>_CLIENT_SECRET` get a generated value), so the bundle runs as-is
- `.env.example` -- the same keys with placeholders for secrets, ready to commit

### `drf`

Generates a Django REST Framework project under `<output>/backend` (Django settings, URLs, ASGI/WSGI, serializers, views, repositories, authentication, and `requirements.txt`).

### `raw`

Generates a runnable raw-ASGI project under `<output>/backend` (its own `app.py`, `requirements.txt`, routes, repositories, and services) without the FastAPI or Django dependency. Its route table applies `api.basePath` and `api.version` exactly once, matching FastAPI. It emits the same `.env` and `.env.example` runtime-setting files as FastAPI, including a generated `JWT_SECRET` when authentication requires one. Custom-operation handler routes are emitted with a request-compatible object carrying path parameters, body, headers, and state.

## The frontend subtarget

The frontend is generated only when the spec contains a `ui:` block with `ui.frontend.pack` set. The only built-in pack is `generic`, which produces a Vite + React + TypeScript + Tailwind project.

```yaml
ui:
  frontend:
    pack: generic
    output: ./web
    overwrite: never   # or "always"
```

Behavior:

- `stackform build app.yaml frontend` writes the project to `ui.frontend.output`, or `./frontend` when it is omitted.
- `stackform build app.yaml frontend -o ./web` overrides the spec output.
- `stackform build app.yaml all` writes the frontend to `<output>/frontend` alongside the backend.
- `overwrite: never` (the default) preserves files you have edited and only refreshes the generated zones; `overwrite: always` rewrites everything.

Failure modes for the standalone `frontend` build (each exits with status 1):

- `No 'ui' block found in the YAML spec.`
- `ui.frontend.pack is required.`

See [UI / Frontend](../ui/frontend.md) for the `ui` block reference.

## Examples

```bash
# Build everything the spec describes (backend, plus frontend/deploy if present)
stackform build myapp.yaml

# Backend only, to a custom directory, targeting DRF
stackform build myapp.yaml backend -t drf -o ./my-django-api

# Frontend only, to a custom directory
stackform build myapp.yaml frontend -o ./web

# Deployment artifacts only
stackform build myapp.yaml deploy -o ./deploy

# Validate against an explicit schema, JSON error output
stackform build myapp.yaml -s ./custom-schema.json --json
```

## Environment variables

`${VAR}` interpolations in the spec are resolved from the environment at build time, after the YAML is loaded and before schema validation. A missing variable without a `:-default` fallback aborts the build (exit 1) with `Environment variable 'X' is required`.

```bash
export MONGO_URI=mongodb://localhost:27017
export MONGO_DB=myapp
stackform build myapp.yaml
```

Secrets are the exception to build-time baking: a confidential OIDC `client_secret` and `JWT_SECRET` are runtime `SecretStr` settings read from `<PROVIDER>_CLIENT_SECRET` / `JWT_SECRET` env vars, never baked as literals. The backend build also emits `.env` (real generated values) and `.env.example` (placeholders); a `deploy` build never bakes a secret into the bundle and instead generates secrets at deploy time via Ansible.

See [Environment variables](../configuration/environment-variables.md) for the full set and which component reads each one.
