# Architecture Review: Datastore Coupling in the Generated Backend

## Problem

The generated FastAPI backend hardwires MongoDB into many layers. Adding
PostgreSQL to the build target would mean editing every one of them, which is
the signal of a structural problem, not a localized gap.

## Two implementations of the same thing

The project has two execution models that each implement CRUD independently:

- The **run server** (`server/...`): pipeline of steps over a `BaseRepository`,
  with repositories resolved through a `RepositoryRegistry`.
- The **generated backend** (`generators/backend/fastapi/...`): emitted code with
  its own `RepositoryBase` + per-operation mixins (`repository_ops.py.jinja`),
  service mixins, and a route factory.

CRUD lives in both. This duplication is the root cause: a clean abstraction was
built in one and not the other.

## Where the database choice lives

Run server: in ONE place. The pipeline, steps, and auth never name MongoDB; they
ask the registry `for_collection(name)` for a repository. Adding a backend means
adding a `BaseRepository` implementation and a branch in the loader.

Generated backend: SCATTERED. The fact that it is MongoDB is written directly
into:

- `app.py` lifespan: imports `connect_db`/`close_db` from `dependencies.mongodb`.
- `routes/_crud_factory.py`: imports `get_database` from `dependencies.mongodb`
  and calls `service_factory(get_database())`.
- `routes/<collection>.py`: `_service_factory(db)` builds `Repository(db)`;
  custom-operation routes import the Mongo `get_database`.
- `repositories/_ops.py`: `RepositoryBase` + CRUD mixins are pymongo.
- `dependencies/mongodb.py`: the connection itself.
- `requirements.txt`: pymongo only.

## What is already clean

The service layer is datastore-neutral. `ServiceBase` only holds a repo and calls
its methods (`self._repo.list()`, `self._repo.COLLECTION`). The repository's
method interface is the real boundary, the same role `BaseRepository` plays in
the run server. The coupling is not in the services; it is in how repositories
are constructed, connected, and named by the surrounding templates.

## Root cause

1. The build target duplicates CRUD instead of reusing the run server's core.
2. Within the build target, repository construction (`Repository(db)`) and
   connection (`get_database`) are inlined into the app/factory/route templates
   rather than owned by a single datastore-aware module.

## Options

### A. Seam-only (build target)
Give the generated backend one datastore-aware module: per-datastore dependency
modules (`mongodb.py`, `postgres.py`), a datastore-agnostic zero-argument service
factory per collection, a neutral `_crud_factory` and `app.py` lifespan, and a
per-datastore repository base selected by datastore type. After this,
datastore-awareness lives in two places (the dependency module and the repository
base) and adding a backend touches two files, not six.

- Pros: contained; unblocks SQL and mixed-datastore codegen.
- Cons: leaves two CRUD implementations (run vs build) to maintain in parallel.

### B. Unify the run and build cores
Make the generated backend reuse one shared repository/CRUD core instead of its
own mixin copy, so there is a single implementation behind both execution models.

- Pros: removes the duplication that allowed the coupling to diverge; one place
  to evolve CRUD, custom operations, and datastore support.
- Cons: large refactor of how code is generated; needs its own plan.

### C. Document only
Keep this review; defer the change.

## Recommendation

The duplication (root cause #1) is why the coupling could exist in one model and
not the other. Option A fixes the symptom and is enough to ship SQL codegen;
Option B fixes the cause. Recommended sequence: do A now to unblock the feature
and stop the bleeding, then schedule B as a deliberate follow-up so the two
execution models converge on one core rather than drifting further apart.

The run-server multi-database work (datastore registry, SQLRepository, custom
operations, migrations) is complete and unaffected by this; it already follows
the single-ownership design proposed here.
