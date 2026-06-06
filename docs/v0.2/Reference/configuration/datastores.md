---
title: "`datastores:`"
description: The `datastores:` section registers one or more databases by name and binds each repository to one.
---

The `datastores:` section registers one or more databases by name. Each repository is bound to one datastore, so a single spec can keep different entities in different databases (for example documents in MongoDB and analytics in PostgreSQL).

A spec that only uses the `mongo:` block (see [`mongo:`](./mongo.md)) is the single-datastore shortcut: it behaves as one default datastore. Use `datastores:` when you need more than one, or a relational database.

## Schema

```yaml
datastores:
  primary:
    type: mongodb
    uri: ${MONGO_URI:-mongodb://localhost:27017}
    database: my-app
    default: true
  warehouse:
    type: postgres
    dsn: ${WAREHOUSE_DSN}
```

## Fields

Each entry is keyed by a datastore name you choose, and has a `type`.

### `type`

Type: string. Required. One of `mongodb` or `postgres`.

### `default`

Type: boolean. Optional.

Marks the datastore used by repositories that do not declare a `datastore:`. When more than one datastore is declared, exactly one must be marked `default: true`. With a single datastore it is the default automatically.

### MongoDB fields

| Field | Type | Description |
|-------|------|-------------|
| `uri` | string | MongoDB connection string. |
| `database` | string | Database name. |

### PostgreSQL fields

| Field | Type | Description |
|-------|------|-------------|
| `dsn` | string | SQLAlchemy async DSN, e.g. `postgresql+asyncpg://user:pass@host:5432/my-app`. |

Always use `${VAR}` interpolation for credentials. See [environment variables](./environment-variables.md).

## Binding a repository

A repository selects its datastore with `datastore:`. Omitting it uses the default.

```yaml
repositories:
  my-repo:
    entity: my-entity
    datastore: warehouse   # omit to use the default datastore
```

Referencing an undeclared datastore is a validation error (`DATASTORE_UNKNOWN_REFERENCE`).

## Schema management

- **`run` server:** tables are created on connect (relational datastores) unless a `migrations/` directory is present, in which case migrations own the schema. See [`migrate`](../cli/migrate.md).
- **Generated backend (`build`):** the generated app creates tables on startup. Each datastore type in use contributes its driver to the generated `requirements.txt`.

## Custom operations per datastore

A custom operation runs against a single datastore, so its query form matches that datastore's type:

- MongoDB repositories use the command form (`query: { command: find, filter: {...} }`).
- PostgreSQL repositories use a parameterized SQL form:

```yaml
repositories:
  events:
    entity: event
    datastore: warehouse
    operations:
      recent:
        query:
          sql: "SELECT * FROM events WHERE user_id = :uid ORDER BY at DESC LIMIT 50"
          params: { uid: "$principal.id" }
```

Bindings (`$principal.*`, route params, `$body.*`) are resolved at request time and passed as bound parameters. Mixing the forms (a SQL query on a MongoDB datastore, or a Mongo command on a relational one) is a validation error (`QUERY_FORM_MISMATCH`).

A single operation cannot span two datastores; combine data from different datastores in a service handler, which can reach any repository.

## Environment overrides

| Variable | Applies to | Description |
|----------|------------|-------------|
| `YAML_API_MONGO_URI` / `YAML_API_MONGO_DB` | default MongoDB datastore (`run`) | Override URI / database. |
| `YAML_API_DB_<NAME>_DSN` | a relational datastore (`run`) | Override the DSN; `<NAME>` is the uppercased datastore name. |
| `DATABASE_URL` | generated backend | Override the relational DSN of the generated app. |

## Example

```yaml
datastores:
  primary:
    type: mongodb
    uri: ${MONGO_URI:-mongodb://localhost:27017}
    database: my-app
    default: true
  warehouse:
    type: postgres
    dsn: ${WAREHOUSE_DSN}

repositories:
  my-entity:
    entity: my-entity      # uses the default (primary)
  events:
    entity: event
    datastore: warehouse   # stored in PostgreSQL
```

## See Also

- [`mongo:`](./mongo.md) -- single-datastore shortcut
- [`migrate`](../cli/migrate.md) -- relational schema migrations
- [Repositories overview](../repositories/overview.md) -- the `datastore:` binding
