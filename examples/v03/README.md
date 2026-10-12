# v0.3 examples

These examples are complete specifications that can be run or compiled from
the repository root. Each directory focuses on a set of v0.3 capabilities and
states which generated backends implement them.

| Example | Demonstrates | Targets |
| --- | --- | --- |
| `crud-pagination` | SQLite CRUD, unique-conflict responses, offset and keyset pagination, and a generated React view | `run`, FastAPI, frontend |
| `password-role` | SQLite-backed password registration/login and role-protected access at `/api/v1` | `run`, FastAPI |
| `access-control` | A role hierarchy, per-operation role access, and `given`/`when` document rules over MongoDB | `build`, FastAPI |
| `access-bindings` | `where` bindings, free route slugs, denial reasons, service `input`/`with`, and access-rule `bind` | `run`, FastAPI, DRF, raw ASGI |
| `secure-session` | RS256 app sessions, rotating refresh tokens, and BFF cookie delivery | `run` except refresh routes, FastAPI |
| `oidc-pkce-dpop` | OIDC authorization-code login with PKCE and DPoP | `run`, FastAPI |
| `mongo-migrations` | Native MongoDB migration lifecycle and unique-index graduation | `run`, FastAPI, DRF, raw ASGI |
| `files` | Filesystem and S3 file datastores, `file` fields, limit precedence, and owner-only downloads | `run`, FastAPI |

Validate any example without contacting its datastore:

```bash
yaml-api build examples/v03/access-bindings/spec.yaml --target fastapi --output /tmp/yaml-v03-build
```

Run the SQLite example directly:

```bash
yaml-api run examples/v03/crud-pagination/spec.yaml
```

Exercise password login and role authorization without MongoDB:

```bash
yaml-api run examples/v03/password-role/spec.yaml

curl -X POST http://127.0.0.1:8000/api/v1/users/register \
  -H 'content-type: application/json' \
  -d '{"email":"user@example.com","displayName":"User","password":"change-this-password"}'

curl -X POST http://127.0.0.1:8000/api/v1/users/login \
  -H 'content-type: application/json' \
  -d '{"email":"user@example.com","password":"change-this-password"}'
```

Registration assigns the configured `user` role in private authentication
metadata; password hashes and role metadata are never returned by CRUD routes.
Use the login response's `token` as a bearer token to call the protected
`GET /api/v1/users` route.

For the OIDC example, configure the provider with this callback URL:
`http://127.0.0.1:8000/api/users/auth/identity/callback`. Then provide its
discovery URL, client secret, and one persistent DPoP key to every app worker:

```bash
export OIDC_DISCOVERY_URL=https://idp.example/realms/example/.well-known/openid-configuration
export OIDC_CLIENT_SECRET=replace-with-provider-secret
export IDENTITY_DPOP_PRIVATE_KEY="$(python -c 'from yaml_api_generator.runtime.dpop import generate_private_key_pem; print(generate_private_key_pem())')"
yaml-api run examples/v03/oidc-pkce-dpop/spec.yaml
```

`tests/integration/test_live_auth_flows.py` exercises that same flow against a
live loopback OIDC server, including PKCE verification, DPoP proofs, automatic
user provisioning, and app-token issuance.

The MongoDB examples expect a local server at `mongodb://localhost:27017` by
default. Their connection can be overridden through the environment variables
documented in the datastore reference.
