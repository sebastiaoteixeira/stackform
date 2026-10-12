---
title: Freely-named single-record tokens
description: Fetch a built-in single-record op by a route-derived token predicate instead of the hardwired `{id}`.
---

## The `{id}` assumption, lifted

The built-in single-record operations &mdash; `get`, `update`, `replace`,
`delete` &mdash; used to hardwire the path token `{id}` and load the record by a
route parameter literally named `id`. Renaming the token silently broke the
fetch: the record never loaded and any ownership / `when:` check evaluated
against nothing.

Under v0.3 a single-record op derives its fetch from the **route template**
instead. A route may name its token freely:

```yaml
controllers:
  categories:
    base_path: /categories
    routes:
      get:
        service: getCategory
        method: GET
        path: /{categoryId}
```

`GET /categories/c1` loads the record whose id field equals `c1` &mdash; the
token name is irrelevant to the fetch.

## The token-derived predicate

The record is located from the path tokens (`{name}` syntax, never a `$` sigil
in the path):

- the **final** token identifies the record by the collection's id field
  (the default `where id = $<token>`);
- each **preceding** token constrains a field of the **same name**, scoping the
  record to its parents.

So a nested path fetches by all of its tokens:

```yaml
      get:
        service: getMember
        method: GET
        path: /orgs/{orgId}/members/{memberId}
```

`GET /orgs/o1/members/m1` loads the `members` record whose `id` is `m1` **and**
whose `orgId` is `o1`. A member that exists under a different org is not found
&mdash; the parent scope is part of the predicate. The scoped fetch reuses the
same `find_one` predicate machinery as the [`where` binding form](./given-where.md);
a single (non-nested) token keeps the direct id fetch.

Every preceding token must name a field declared on the collection's entity.
Generation fails with `ROUTE_LOCATOR_FIELD_UNKNOWN` when it does not. This
prevents a misspelled scope from becoming a permanent 404 in MongoDB or a
runtime column error in SQL.

When an access rule needs a different field mapping than same-name (for example
a parent column named `org_id`), declare it explicitly with the
[`where` binding form](./given-where.md) in the rule's `given:`; that binding
is respected and resolves its `$<token>` references against the route slugs.

## Per-token error

A request that reaches a single-record op without one of its tokens fails with a
message naming the actual token:

```
Missing route parameter: categoryId
```

Framework-generated routes declare the actual token names, so FastAPI and DRF
also expose the correct path parameters in request validation and OpenAPI/schema
output.

## Fetch and mutation semantics

The route-derived predicate applies consistently to `get`, `update`, `replace`,
and `delete` in both `stackform run` and generated FastAPI, DRF, and raw ASGI
backends. Scoped writes are a single repository operation: the complete parent
and id predicate is applied by `update_by`, `replace_by`, or `delete_by`. The
implementation does not fetch by scope and then mutate by id, so a concurrent
change cannot move a record across the parent boundary between those actions.
Fields supplied by the route predicate are immutable for that request: update
and replacement payload values cannot override the id or parent scope.

Custom runtime repositories must implement these `BaseRepository` methods in
addition to `find_one`:

```python
async def update_by(collection_name, criteria, payload): ...
async def replace_by(collection_name, criteria, payload): ...
async def delete_by(collection_name, criteria): ...
```

Each method returns the affected document, or `None` when the complete predicate
does not match. The built-in MongoDB and SQL adapters and all generated
repositories implement this contract.

## v0.2 compatibility

v0.2 built-in single-record ops always use the `{id}` convention. Runtime and
generated backends continue to load directly by `id`, and a missing runtime
parameter yields the exact legacy message `Missing route parameter: id`.
Freely-named and nested record predicates are enabled only when the spec version
is `0.3`.
