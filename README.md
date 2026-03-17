# YAML API Generator

A YAML-driven REST API engine that generates fully functional CRUD APIs backed by MongoDB. Define your data model, authentication, and access rules in a declarative YAML file — get a running FastAPI server or compiled Django REST Framework project with zero hand-written server code.

## Installation

Requires Python 3.11+ and a running MongoDB instance.

```bash
pip install -e .
```

Start MongoDB locally (requires Docker):

```bash
docker-compose up -d
```

## Usage

### Development server

Run a live FastAPI server directly from a YAML spec:

```bash
yaml-api dev spec.yaml
```

Options:

- `--host` — bind address (default: `127.0.0.1`)
- `--port` — bind port (default: `8000`)
- `--schema` — path to a custom JSON Schema file (auto-detected from spec version if omitted)

### Compile to a standalone project

Generate a full project (Django REST Framework or FastAPI):

```bash
yaml-api compile spec.yaml --target drf --output ./my-api
```

Options:

- `--target` — `fastapi`, `drf`, or `raw` (default: `fastapi`)
- `--output` — output directory (default: `./target`)
- `--schema` — path to a custom JSON Schema file (auto-detected if omitted)
