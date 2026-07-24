# Unique violation `409 Conflict`

Writing a record whose value collides with a `unique` field raises a conflict at
the datastore boundary instead of surfacing as an opaque `500`. Both backends map
their native duplicate-key error to a single domain `ConflictError`:

- SQL: SQLAlchemy `IntegrityError` for a unique constraint.
- Mongo: `DuplicateKeyError`.

The runtime answers such a request with `409 Conflict` and a body that names the
offending field:

```json
{ "detail": "Duplicate value violates unique constraint on field 'email'" }
```

This applies to `create`, `update`, `replace`, and `upsert` on any field declared
`unique: true`. When the field cannot be recovered from the backend error, the
body falls back to `{"detail": "Duplicate value violates a unique constraint"}`.

The behavior is not version-gated: it holds for `0.2` and `0.3` specs alike, and
replaces only the former unhandled-error path, so no successful response changes.
