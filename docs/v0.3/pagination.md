---
title: Pagination
description: Paged list responses declared at the controller, with implicit repository primitives and service mapping underneath.
---

# Pagination (v0.3)

Pagination is decomposed across three layers and declared **explicitly only at
the controller**. The repository exposes generic primitives implicitly; the
service maps the request onto them implicitly. All pagination behavior is gated
on `version: "0.3"`. It is implemented by `stackform run` and by generated
FastAPI, DRF, and raw ASGI backends.

## The three layers

### Repository (implicit primitives)

A list-shaped operation accepts a fixed set of all-optional primitives and
applies whichever are populated:

| primitive | meaning |
|-----------|---------|
| `limit`   | maximum rows returned (positive for keyset; non-negative for offset) |
| `skip`    | rows skipped before returning (`int >= 0`) |
| `sort`    | ordered list of `{ field, dir: asc\|desc }` |
| `bounds`  | ordered comparison keys compiled lexicographically |
| `count`   | `none` \| `exact` |

Application is uniform and backend-agnostic:

```
q     = filter AND compile(bounds)
rows  = find(q).sort(sort).skip(skip).limit(limit)
total = count(filter) when count != none
```

`filter` is the route's scoping predicate, including the row filter of its
access rules (not a primitive); it ANDs into `bounds`. Omitting every
primitive yields the unbounded list.

`bounds` is the one non-trivial primitive. Each bound is an ordered tuple of
comparison keys that compiles to a **lexicographic** comparison, so a keyset
page over a compound sort is a single bound expanded into the canonical
OR-of-AND form. For a sort `(a asc, b asc)` and a cursor `(a0, b0)`:

```
(a > a0) OR (a = a0 AND b > b0)
```

Both backends render that same expansion: Mongo as an `$or` of equality-pinned
prefixes, SQL as an `sa.or_` of `sa.and_` groups.

### Service (implicit mapping)

A repository-backed service inherits the operation's primitive contract and
passes the well-known pagination inputs straight through. An explicit `with:`
is only ever for domain inputs -- never for pagination primitives. The query
parameters map onto primitives as follows:

| query param | primitive |
|-------------|-----------|
| `limit`     | `limit` (defaulted to `size.default`, clamped to `size.max`) |
| `offset`    | `skip` |
| `after`     | `bounds` derived from `sort` (strict `>`/`<` per direction, compound) |

### Controller (explicit strategy -- the only strategy site)

```yaml
controllers:
  posts:
    service: posts
    operations:
      list:
        pagination:
          strategy: offset        # offset | keyset
          size: { default: 20, max: 100 }
          count: none             # none | exact (default none)
          onOverflow: clamp       # clamp | reject             (default clamp)
          envelope: true          # default false
```

## Strategies

### offset

`?limit=&offset=`. Stable order comes from the declared `sort` (recommended).
`size.max` is enforced server-side: an over-limit request is clamped, or
rejected with `422` when `onOverflow: reject`.

### keyset

`?after=&limit=` with a **required** `sort`. The last sort field is the
tiebreaker and must be unique and indexed, and every sort field must be required
and non-null; otherwise the build fails. `after`
is an opaque base64url token encoding the previous page's sort position; the
service turns it into a compound lexicographic bound. Forward paging is stable
under concurrent inserts. Keyset page sizes must be positive because a zero-item
page cannot provide a continuation position. Invalid, negative, or zero keyset
limits return `422`.

```yaml
pagination:
  strategy: keyset
  size: { default: 20, max: 100 }
  sort:
    - { field: score, dir: desc }
    - { field: id }          # unique tiebreaker
  envelope: true
```


## Envelopes

With `envelope: false` (the default) the response is a bare array. With
`envelope: true`:

| strategy | envelope |
|----------|----------|
| offset   | `{ items, limit, offset, total? }` |
| keyset   | `{ items, next, hasMore, total? }` |

`total` is present only when `count != none`. For keyset, `next` is the token
to pass as `after` for the following page (`null` on the last page), and
`hasMore` reflects whether further rows exist.

## Build-time errors

| code | raised when |
|------|-------------|
| `SCHEMA_VALIDATION_ERROR` | an unknown key, a `strategy` other than `offset`/`keyset`, a `count` other than `none`/`exact`, an `onOverflow` other than `clamp`/`reject`, a missing or non-integer `size.default`/`size.max`, or a sort entry without `field` or with a `dir` other than `asc`/`desc` |
| `PAGINATION_UNSUPPORTED` | `pagination` is set on a route whose operation is not a repository list |
| `PAGINATION_INVALID_SIZE` | `size.default` exceeds `size.max` |
| `PAGINATION_SORT_FIELD_UNKNOWN` | a sort field is not a field of the entity |
| `PAGINATION_KEYSET_SORT_REQUIRED` | keyset declared without a `sort` |
| `PAGINATION_KEYSET_TIEBREAKER_NOT_UNIQUE` | the last keyset sort field is not unique/indexed |
| `PAGINATION_KEYSET_SORT_FIELD_NULLABLE` | a keyset sort field is not required/non-null |
