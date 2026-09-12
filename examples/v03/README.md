# v0.3 examples

These examples are complete specifications that can be run or compiled from
the repository root. Each directory focuses on a set of v0.3 capabilities and
states which generated backends implement them.

| Example | Demonstrates | Targets |
| --- | --- | --- |
| `crud-pagination` | SQLite CRUD, unique-conflict responses, offset and keyset pagination, and a generated React view | `run`, FastAPI, frontend |
| `access-bindings` | `where` bindings, free route slugs, denial reasons, service `input`/`with`, and access-rule `bind` | `run`, FastAPI, DRF, raw ASGI |
| `secure-session` | RS256 app sessions, rotating refresh tokens, and BFF cookie delivery | `run` except refresh routes, FastAPI |
| `oidc-pkce-dpop` | OIDC authorization-code login with PKCE and DPoP | `run`, FastAPI |
| `mongo-migrations` | Native MongoDB migration lifecycle and unique-index graduation | `run`, FastAPI, DRF, raw ASGI |

Validate any example without contacting its datastore:

```bash
yaml-api build examples/v03/access-bindings/spec.yaml --target fastapi --output /tmp/yaml-v03-build
```

Run the SQLite example directly:

```bash
yaml-api run examples/v03/crud-pagination/spec.yaml
```

The MongoDB examples expect a local server at `mongodb://localhost:27017` by
default. Their connection can be overridden through the environment variables
documented in the datastore reference.
