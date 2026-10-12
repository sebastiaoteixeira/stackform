---
title: "`mongo:`"
description: The `mongo:` section sets the compile-time MongoDB connection defaults.
---

The `mongo:` section sets the MongoDB connection defaults that get baked into the
generated app. The whole block is optional; when omitted, the defaults below apply.

This is the single-datastore shortcut: a spec with `mongo:` behaves as one default MongoDB datastore. To use more than one database, or a relational database, use [`datastores:`](./datastores.md) instead.

## Schema

```yaml
mongo:
  uri: mongodb://localhost:27017
  database: yaml_api
```

## Fields

### `uri`

Type: string. Optional. Default: `mongodb://localhost:27017`.

Full MongoDB connection string. Supports all standard MongoDB URI options (auth, replica sets, TLS, etc.).

```yaml
# Local
uri: mongodb://localhost:27017

# With credentials
uri: mongodb://user:password@host:27017

# Atlas
uri: mongodb+srv://user:password@cluster.mongodb.net

# Replica set
uri: mongodb://host1:27017,host2:27017/?replicaSet=rs0
```

Always use `${VAR}` interpolation for credentials. Interpolation runs per
string scalar after the YAML is loaded, so the value can come entirely from the
environment, optionally with a fallback for local development:

```yaml
uri: ${MONGO_URI}
# or with a fallback for local dev:
uri: ${MONGO_URI:-mongodb://localhost:27017}
```

### `database`

Type: string. Optional. Default: `yaml_api`.

Name of the MongoDB database to use. All collections live in this database. Each
repository name becomes a collection name inside it (no pluralization).

```yaml
database: yaml_api
database: ${MONGO_DB:-yaml_api}
```

## Runtime vs spec

The values here are compile-time defaults only. The running app reads its
connection from the environment and falls back to these defaults:

- Generated backend (`stackform build`): reads `MONGO_URI` and `MONGO_DB`. If
  those are unset, it uses `mongodb://localhost:27017` and `yaml_api` (the same
  defaults as this block), not the spec values.
- Dev server (`stackform run`): reads `YAML_API_MONGO_URI` and `YAML_API_MONGO_DB`,
  falling back to the `mongo.uri` / `mongo.database` values from the spec.

This means you can ship one spec and point each environment at a different
database without editing the YAML.

## Deployment

When you generate a deploy bundle (`stackform build myapp.yaml deploy`), the
`mongo.uri` decides whether MongoDB is bundled:

- If `uri` is omitted or points at `localhost` / `127.0.0.1`, the generated
  `docker-compose.yml` includes a `mongodb` service (`mongo:8`) backed by a
  `mongo_data` volume, and the app depends on it.
- If `uri` points at a remote host (for example MongoDB Atlas), no MongoDB
  container is added; the app connects out to the URI you provide via the
  `MONGO_URI` environment variable.

The generated compose file sets `MONGO_DB` to `mongo.database` by default
(overridable through the environment), and the bundled MongoDB has no
authentication, so keep it on the internal Docker network.

The deploy bundle bakes nothing secret. Backend secrets (`JWT_SECRET`, each
`<PROVIDER>_CLIENT_SECRET`) are referenced as bare `${VAR}` and generated at deploy
time by Ansible; see [Secrets in the generated
deploy](./environment-variables.md#secrets-in-the-generated-deploy).

## Example

```yaml
mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-yaml_api}
```
