# Design: Polyglot Persistence (PostgreSQL support)

## Goal

Support multiple databases in a single spec, modeled on the multi-provider auth
architecture: register several datastores by name and bind each collection to
one. PostgreSQL is the first relational target alongside MongoDB.

## Decisions

### Datastore registry

- New `datastores:` block: named, typed entries
  (`main: { type: mongodb, ... }`, `warehouse: { type: postgres, ... }`).
- `collection.datastore:` binds a collection to one datastore; unbound
  collections use a configured default.
- Backward compatible: a bare `mongo:` spec is the single-default-datastore
  case and keeps working unchanged.

### Repository registry

- `loader` returns a registry (name to `BaseRepository`) plus the
  collection-to-datastore binding, replacing the single-repository return.
- `BaseRepository` and its six methods are unchanged; there are simply several
  instances, one per configured datastore.
- `RequestContext` gains `repository_for(collection)`. `ctx.repository` remains
  the repository bound to the route's collection for ordinary CRUD. The
  pipeline binds the correct repository per route.

### Relational engine

- One `SQLRepository` on SQLAlchemy Core + asyncpg, serving relational dialects.
  MongoDB stays its own implementation. The seam between them is
  `BaseRepository`.
- `table_from_collection()` builds a `sqlalchemy.Table` from the spec's typed
  fields:
  - string to TEXT (VARCHAR(maxLength) when set), number to NUMERIC,
    boolean to BOOLEAN, datetime to TIMESTAMPTZ, enum to TEXT + CHECK,
    array and object to JSONB, id to primary key.
  - required to NOT NULL; min/max/minLength/maxLength to CHECK constraints.
- IDs are app-generated UUID strings (uuidv4/uuidv7/natural); PK is UUID/TEXT.
  No ObjectId in the SQL path.

### Schema lifecycle

- `create_all()` at connect, by default, for both `run` and `build`.
- `yaml-api migrate` graduates a project to versioned Alembic migrations:
  - `migrate new` autogenerates a revision from the spec; first run scaffolds
    Alembic against our metadata, emits the initial revision, and stamps the
    existing database at baseline.
  - `migrate up [--to REV]` (default head), `migrate down [--to REV]`
    (default one step), `migrate status`, `migrate history`.
  - Presence of a migrations directory flips runtime off `create_all()`.
- The generated backend (`build`) emits a plain Alembic scaffold
  (`alembic.ini`, `env.py` wired to our metadata, `versions/`); operators run
  standard Alembic. No yaml-api dependency in the deployed app.

### Custom operations

Layered by scope and expressed natively per store:

- Single-store declarative (A1):
  - MongoDB collections: existing command DSL (arbitrary `filter`/`pipeline`).
  - PostgreSQL collections: raw parameterized `sql:` with an explicit `params:`
    map (for example `params: { uid: "$principal.id" }`). No structured `where`
    form; each store gets its native, unlimited query surface.
- Single-store imperative (B): Python `handler:` bound to one repository, for
  logic that is not a single store command.
- Cross-store (service layer only): a single operation never spans two
  datastores. Combining stores is a service handler that receives the registry
  via `ctx.repository_for(...)`. Cross-store writes have no shared transaction
  (documented limitation).

### Closing the run/build gap

Today declarative custom query ops run only in `build`; the `run` server raises
on non-CRUD operations. The fix is a first-class pipeline step:

- Add `RepositoryOperationStep`, which resolves the compiled `IROperation` from
  the bound repository and runs it. The pipeline builder dispatches non-CRUD
  operations through this step instead of raising.
- Each backend repository compiles an `IROperation` into a callable (MongoDB
  builds the driver call from the query dict; SQL builds a parameterized
  statement). `build` emits that code; `run` compiles it at startup. Same
  source of truth, both models agree, for both MongoDB and PostgreSQL.

## Out of scope (deferred)

- Neutral cross-DB query DSL (A2).
- Declarative cross-store enrich (C).
- Cross-store service handlers (D) as a built feature: the `repository_for`
  hook is added now; the handler ergonomics belong to the custom-logic effort.
- Unique constraints / indexes from spec (no parity today).
- Relational targets beyond PostgreSQL (the SQLAlchemy layer enables them; not
  targeted now).
- Cross-store transactions (inherently unsupported).

## Implementation slices

Ordered; run-server path proven before generator templates.

1. Datastore registry config: `datastores:` parsing, `collection.datastore:`
   binding, default resolution, `mongo:` backward compatibility. No behavior
   change for existing specs.
2. Repository registry: loader returns registry + binding;
   `RequestContext.repository_for`; pipeline binds per route.
3. `table_from_collection` (type mapping + constraints) and `SQLRepository`
   (six CRUD methods) on SQLAlchemy Core + asyncpg; `create_all()` at connect.
   Wire the `run` server end to end; integration test against PostgreSQL.
4. `RepositoryOperationStep` and per-backend `IROperation` compilation; close
   the run/build gap for MongoDB and PostgreSQL declarative ops in `run`.
5. `yaml-api migrate` subgroup over Alembic (baseline/stamp on first run).
6. Codegen: SQL repository templates, `dependencies/postgres.py`, SQL custom-op
   rendering, Alembic scaffold emit; selected per datastore type.