# YAML API Generator

A YAML-driven REST API engine that generates fully functional CRUD APIs backed by MongoDB. Define your data model, authentication, and access rules in a declarative YAML spec — get a running FastAPI server, a compiled standalone project, and an optional React frontend with zero hand-written code.

## Requirements

- Python 3.11+
- Node.js 18+ (only for frontend generation)
- Docker (for local MongoDB)

## Installation

```bash
pip install -e .
```

Start MongoDB locally:

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

Generate a full project (backend + optional frontend):

```bash
yaml-api compile spec.yaml --output ./target
```

Outputs:

- `target/backend/` — standalone FastAPI project
- `target/frontend/` — React app (only if the spec has a `ui` block)

Options:

- `--target` — `fastapi`, `drf`, or `raw` (default: `fastapi`)
- `--output` — output directory (default: `./target`)
- `--schema` — path to a custom JSON Schema file (auto-detected if omitted)

Run the compiled backend:

```bash
cd target/backend
pip install -r requirements.txt
python app.py
```

Run the compiled frontend:

```bash
cd target/frontend
npm install
npm run dev
```

### Generate frontend only

```bash
yaml-api frontend spec.yaml
```

Output directory is read from `ui.frontend.output` in the spec, or overridden with `--output`.

## Example

Try the blog example (backend + frontend):

```bash
docker-compose up -d
yaml-api compile examples/v02/api-with-ui.yaml
cd target/backend && pip install -r requirements.txt && python app.py &
cd target/frontend && npm install && npm run dev
```

Or the admin panel example:

```bash
yaml-api compile examples/v02/api-with-admin.yaml
cd target/backend && pip install -r requirements.txt && python app.py &
cd target/frontend && npm install && npm run dev
```

## YAML spec — key concepts

### API config

```yaml
version: "0.2"

api:
  basePath: /api
  version: v1
  port: 8000          # backend port baked into compiled app (default: 8000)
  cors:
    origins: ["http://localhost:5173"]
```

### Entities, repositories, controllers

```yaml
entities:
  user:
    type: auth
    auth:
      identifier: email
      via: password
      roles: role
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      role: { type: enum, values: [admin, user], default: user }

repositories:
  users:
    entity: user

controllers:
  users:
    service: users
    base_path: /users
    access: "*"
    operations:
      register: { access: public }
      login: { access: public }
```

### Frontend UI pack

```yaml
ui:
  frontend:
    pack: examples/packs/blog    # path to a pack directory
    output: ./frontend-output

  views:
    posts-list:
      path: /posts
      component: grid
      props:
        collection: post-feed
```

Built-in packs in `examples/packs/`:

- `blog` — grid/card/article/form layout for content sites
- `admin` — PocketBase-style admin panel with sidebar, table, and modals
