---
title: Unique violations and `409 Conflict`
description: Unique constraints are enforced consistently by SQL and MongoDB in the runtime server and generated backends.
---

## Response contract

Writing a record whose value collides with a `unique` field raises a conflict at
the datastore boundary instead of surfacing as an opaque `500`. Repository code
maps the native duplicate-key error to a single domain `ConflictError`:

- SQL: only SQLAlchemy `IntegrityError` instances identified as unique-constraint
  violations. Other integrity failures keep their original error.
- MongoDB: `DuplicateKeyError` and duplicate entries in `BulkWriteError`.
  Non-duplicate bulk failures keep their original error.

The HTTP layer answers with `409 Conflict` and a body that names the offending
field when the datastore reports it:

```json
{ "detail": "Duplicate value violates unique constraint on field 'email'" }
```

This applies to all built-in write paths, predicate-based updates and
replacements, runtime custom SQL and MongoDB writes, and generated MongoDB custom
write operations. The live FastAPI and raw-ASGI servers and generated FastAPI,
DRF, and raw-ASGI backends use the same response contract.

When the field cannot be recovered from the backend error, the body falls back
to `{"detail": "Duplicate value violates a unique constraint"}`. The response
never includes the conflicting value, SQL text, driver message, or constraint
internals.

## Constraint creation

For a field declared `unique: true`, SQL tables include a unique constraint and
MongoDB startup creates a unique partial index for non-null values. A collision
can still occur after request validation because uniqueness is enforced
atomically by the datastore; the repository translation is therefore the
authoritative error boundary.

Where the MongoDB index comes from depends on whether the spec has graduated to
versioned migrations: see
[MongoDB migrations](./mongo-migrations.md), which also lists the runtimes that
still create those indexes on connect. The response contract above is the same
either way — it depends on the index existing, not on what created it.

The behavior is not version-gated: it holds for `0.2` and `0.3` specs alike, and
replaces only the former unhandled-error path, so no successful response changes.
