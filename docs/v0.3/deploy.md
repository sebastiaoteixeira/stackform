---
title: Deploy
description: Ship the generated backend with hand-written packages, extra processes and a hand-written frontend to several environments, from a registry, over SSH or built on the host.
---

The `deploy:` section turns a spec into a deploy bundle: a Docker Compose
project or systemd units, plus an Ansible playbook that releases them. Every key
on this page is optional. A spec that uses none of them generates the same
bundle as a v0.2 spec.

The keys from `docker.registry` onwards are v0.3 behavior. A v0.1 or v0.2 spec
that sets them gets a `DEPLOY_KEY_IGNORED` warning and keeps its old bundle.

```yaml
deploy:
  runtime: docker
  name: shop
  port: 8000
  docker:
    registry: ghcr.io/example/shop
    delivery: registry
    retain: 3
  backend:
    packages: [extensions]
    system_packages: [libpq5]
    processes:
      api: { asgi: extensions.main:app }
      worker: { command: python -m extensions.worker }
  frontend:
    source: web
    env: [VITE_API_BASE_URL]
    secrets: [NPM_TOKEN]
  services:
    mailpit: { image: axllent/mailpit:latest, profiles: [local] }
  environments:
    staging:
      env: { BIND_ADDRESS: 127.0.0.1, APP_PORT: "8001", FRONTEND_PORT: "8081" }
      secrets: [SMTP_PASSWORD]
    production:
      env: { APP_PORT: "8000" }
      secrets: [SMTP_PASSWORD]
```

`examples/valid/deploy-extension.yaml` is a complete version of this spec, with
its package and frontend directories in `examples/valid/deploy-extension/`.

## Backend

### `backend.packages`

Directories of hand-written Python code. Each path is relative to the spec and
must lie below the spec directory, outside the output directory. A package is
copied into the bundle as `packages/<name>` and imported as module `<name>`, so
its directory name must be a Python identifier other than `app`, the generated
module.

Every `requirements.txt` found under a package is installed, in path order.

| Runtime | How the package runs |
| --- | --- |
| docker | A `FROM generated` stage installs the requirements and copies the package next to the generated app. The package is a named build context (`additional_contexts`). |
| systemd | The package is synced to `/opt/<project>/packages/<name>`, its requirements are installed in the project's virtualenv, and every unit gets `PYTHONPATH=/opt/<project>/packages`. |

### `backend.system_packages`

Debian packages the hand-written code needs, such as `libpq5`. They are
installed in the package stage of the image, or on the host with systemd.

### `backend.processes`

The long-running backend processes. Each process sets exactly one of:

| Field | Description |
| --- | --- |
| `asgi` | `module:attribute` of an ASGI app served by uvicorn on `deploy.port`. Its module must be `app` or one of the packages. |
| `command` | Any other command, as a string or a list of arguments. |
| `env` | Optional environment values of this process only. |
| `depends_on` | Docker only: service names mapped to `service_started`, `service_healthy`, or `service_completed_successfully`. Local datastore dependencies are retained. |

Exactly one process declares `asgi`. Without `processes`, the backend runs one
process, `app`, serving the generated `app:app`. Process names must not clash
with `services`, datastore services or `frontend`.

| Runtime | Each process becomes |
| --- | --- |
| docker | A compose service sharing the backend image. Only the `asgi` process builds the image, publishes the port and has a health check. |
| systemd | A unit `<project>-<process>.service`. The generated `app` process keeps the unit `<project>.service` it has always had. |

A one-shot setup service must be a dependency with
`service_completed_successfully` of a long-running service. For example,
`api.depends_on: { storage-init: service_completed_successfully }` waits for
bucket creation and makes Compose's `--wait` treat its successful exit as
expected. Self-dependencies and unknown service names fail generation.

## Frontend

By default the bundle serves the generated frontend when the spec has a `ui:`
block. `frontend.source` replaces it with a hand-written app (docker only).

| Field | Default | Description |
| --- | --- | --- |
| `source` | — | Directory with a `package.json`, below the spec directory. `npm ci` runs when a `package-lock.json` is present, `npm install` otherwise. |
| `build` | `npm run build` | Build command. |
| `output` | `dist` | Build output directory served by nginx. |
| `env` | `[]` | Names served at runtime as `window.__CONFIG__` from `/config.js`. |
| `args` | `[]` | Build arguments, for values that must be baked into the bundle. |
| `secrets` | `[]` | BuildKit secrets available to dependency installation, such as `NPM_TOKEN`. Secret mounts are absent during the app build; commands must not copy credentials into output. |

A name may appear in only one of `env`, `args` and `secrets`.

Runtime configuration keeps one image valid for every environment: nginx renders
`/config.js` from the container environment when it starts. Load it before the
app and read it first:

```html
<script src="/config.js"></script>
```

```js
const apiBaseUrl = window.__CONFIG__?.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE_URL;
```

nginx also proxies `/api` to the `asgi` process. The generated frontend reads
`VITE_API_BASE_URL` the same way.

## Images (docker)

| Field | Default | Description |
| --- | --- | --- |
| `docker.registry` | — | Repository prefix of the release images, `<registry>/backend` and `<registry>/frontend`. Exclusive with `docker.image`. |
| `docker.delivery` | `registry` | How images reach the host: `registry` pulls them, `ssh` copies a saved archive. |
| `docker.retain` | `3` | Old releases kept on the host besides the running and the previous one. |

The spec never names a tag. Each release is tagged by `IMAGE_TAG`, usually the
commit, so CI builds and pushes with:

```bash
IMAGE_TAG=$GITHUB_SHA docker buildx bake -f docker-compose.yml api frontend --push
```

Without a registry, images are named `<name>/backend` and `<name>/frontend` and
are built on the host from the shipped bundle, as in v0.2. Environments that
ship packages, processes or a frontend source need either `docker.registry` or
`docker.delivery: ssh`.

`services` entries accept `profiles`, so local-only helpers such as a mail
catcher start with `docker compose --profile local up` and never in a release.

### Shared-host resource limits

`docker.memory_limits` maps generated Compose service names (backend processes,
`frontend`, and local datastores) to positive integer sizes such as `192m` or
`1g`. Each sets both `mem_limit` and `memswap_limit`, preventing that container
from using swap. Unknown service names fail generation. Extra `services` use
Compose's native `mem_limit` and `memswap_limit` fields instead.

`docker.mongo_cache_gb` sets `mongod --wiredTigerCacheSizeGB` for local MongoDB
services. It must be between 0.256 and 10000, and requires a local MongoDB.
The cache is only part of MongoDB's memory: leave room for connections and other
allocations when choosing its container limit.

```yaml
  docker:
    memory_limits: { api: 192m, worker: 128m, mongodb: 512m, frontend: 32m }
    mongo_cache_gb: 0.256
```

These settings require the Docker runtime and are unset by default. Limits
contain memory use; they do not establish that an application fits. Measure a
representative workload and account for other host services before deployment.
See [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)
and [MongoDB WiredTiger caching](https://www.mongodb.com/docs/manual/core/wiredtiger/).

Frontend images build on Node 22 Alpine. The generated Compose file permits a
missing `.env`, so `docker buildx bake --print` and CI builds work directly from
the bundle. Ansible still requires declared secrets and writes the runtime
`.env` before starting containers.

## Environments

Each environment is an inventory group with its own project, `<name>-<env>`,
deployed to `/opt/<name>-<env>`.

| Field | Description |
| --- | --- |
| `env` | Literal values written to the remote `.env`. Values are strings, so quote ports. |
| `secrets` | Names read on the Ansible controller, from CI secrets. The release fails when one is empty. |

Environment names match `[a-z][a-z0-9_-]*`. A name is either a literal or a
secret, never both, and secrets the backend generates itself, such as
`JWT_SECRET`, are not listed: they are created on the host on the first release
and reused afterwards.

With docker, `BIND_ADDRESS`, `APP_PORT` and `FRONTEND_PORT` choose where an
environment listens, so staging and production can share a host. systemd units
listen on `deploy.port`, so give each environment its own host.

Without `environments`, the bundle has one environment, `default`, whose host
comes from the CLI, and keeps the `/opt/<name>` project it has always had.

## Releasing

For a host where the runtime is already installed, extra vars can set
`deploy_install_runtime: false` to skip the runtime provisioning role. With
Docker, an account already allowed to use the daemon can also set
`ansible_become: false` and `app_dir` to a directory it owns. Provision Docker
and that access separately before using these overrides.

```bash
ansible-galaxy collection install -r requirements.yml
DEPLOY_HOST=203.0.113.10 DEPLOY_USER=deploy SMTP_PASSWORD=... \
  ansible-playbook playbook.yml -e deploy_environment=staging -e image_tag=$GITHUB_SHA
```

`DEPLOY_SSH_PORT` defaults to 22. With `delivery: registry`, also export
`REGISTRY_USERNAME` and `REGISTRY_PASSWORD`; the host logs out after pulling.
With `delivery: ssh`, save the images next to the playbook first:

```bash
docker save ghcr.io/example/shop/backend:$GITHUB_SHA ghcr.io/example/shop/frontend:$GITHUB_SHA \
  | zstd > images.tar.zst
```

The remote `.env` is rendered on every release from, in order of precedence:
the bundle defaults, the generated secrets, `env`, `secrets` and, with docker,
`IMAGE_TAG`. Put values under `app_env` in `group_vars/<env>.yml` rather than
in a `.env` next to the bundle, which is never shipped.

A docker release starts with `wait`. When it fails, the previous image tag is
restored and the play fails. Images older than `retain` releases are then
pruned. A systemd release syncs the app, installs the requirements and restarts
every unit.

## Validation errors

| Code | Cause |
| --- | --- |
| `DEPLOY_DOCKER_ONLY` | `docker.registry` or `frontend.source` with the systemd runtime |
| `DEPLOY_IMAGE_REGISTRY_EXCLUSIVE` | Both `docker.image` and `docker.registry` |
| `DEPLOY_REGISTRY_REQUIRED` | Environments ship built images by registry, but no registry is set |
| `DEPLOY_PACKAGE_OUTSIDE_SPEC`, `DEPLOY_PACKAGE_NOT_FOUND` | A package is not a directory below the spec |
| `DEPLOY_PACKAGE_NAME_INVALID`, `DEPLOY_PACKAGE_DUPLICATE` | A package name is not an importable, unique module other than `app` |
| `DEPLOY_ASGI_PROCESS_COUNT` | Not exactly one `asgi` process |
| `DEPLOY_ASGI_MODULE_UNKNOWN` | The `asgi` module is neither `app` nor a package |
| `DEPLOY_PROCESS_NAME_CLASH` | A process is named like a service or `frontend` |
| `DEPLOY_FRONTEND_OUTSIDE_SPEC`, `DEPLOY_FRONTEND_NOT_FOUND` | The frontend source is not below the spec or has no `package.json` |
| `DEPLOY_FRONTEND_NAME_OVERLAP` | A name is in more than one of `env`, `args` and `secrets` |
| `DEPLOY_ENV_VALUE_INTERPOLATED` | An environment value still holds a `${...}` placeholder |
| `DEPLOY_ENV_SECRET_OVERLAP` | A name is both a literal and a secret |

`examples/invalid/deploy-*.yaml` show several of them.
