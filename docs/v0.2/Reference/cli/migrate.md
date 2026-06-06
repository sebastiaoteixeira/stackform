---
title: "`yaml-api migrate`"
description: Manage versioned schema migrations for relational datastores using Alembic.
---

`yaml-api migrate` manages versioned schema migrations for a relational (PostgreSQL) datastore. By default a relational datastore creates its tables on connect; `migrate` graduates a project to versioned migrations once you need reproducible, reviewable schema evolution.

Migrations require a synchronous driver (`psycopg`), which is installed with the generator.

## Commands

| Command | Description |
|---------|-------------|
| `migrate new <spec> [-m MESSAGE]` | Autogenerate a revision from the spec. Scaffolds the Alembic environment on first use. |
| `migrate up <spec> [--to REV]` | Apply migrations forward. Default target is `head`. |
| `migrate down <spec> [--to REV]` | Revert migrations. Default target is one step back. |
| `migrate status <spec>` | Show the current revision. |
| `migrate history <spec>` | List revisions. |

All commands take the spec file as their argument. `--datastore NAME` selects the relational datastore when the spec declares more than one.

## Graduating from create_all

On the first `migrate new`, the Alembic environment is scaffolded next to the spec (a `migrations/` directory) and an initial revision is generated from the spec's tables. If the target database already contains those tables (created earlier by the on-connect `create_all`), it is stamped at the baseline rather than re-created. Once `migrations/` exists, the `run` server stops creating tables on connect and defers to migrations.

```bash
# graduate and apply
yaml-api migrate new my-spec.yaml -m "initial schema"
yaml-api migrate up my-spec.yaml

# evolve: change the spec, then
yaml-api migrate new my-spec.yaml -m "add column"
yaml-api migrate up my-spec.yaml
```

## Targets

`--to` accepts any Alembic target: `head`, `base`, a revision id, or relative forms like `+1` / `-1`.

```bash
yaml-api migrate up my-spec.yaml --to head
yaml-api migrate down my-spec.yaml --to -1
```

## See Also

- [`datastores:`](../configuration/datastores.md) -- declaring relational datastores
- [`run`](./run.md) -- the development server
