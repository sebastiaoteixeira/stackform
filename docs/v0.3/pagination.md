---
title: Pagination
---

# Pagination (v0.3)

Pagination is decomposed across three layers and declared **explicitly only at
the controller**. The repository exposes generic primitives implicitly; the
service maps the request onto them implicitly. All pagination behavior is gated
on `version: "0.3"`. It is implemented by `yaml-api run`. Generated FastAPI,
DRF, and raw backends reject paginated operations at build time because their
emitted repositories still list unbounded; they never silently ignore the
declaration.

## The three layers

### Repository (implicit primitives)

A list-shaped operation accepts a fixed set of all-optional primitives and
applies whichever are populated:

| primitive | meaning |
|-----------|---------|
| `limit`   | maximum rows returned (`int >= 0`) |
| `skip`    | rows skipped before returning (`int >= 0`) |
| `sort`    | ordered list of `{ field, dir: asc\|desc }` |
| `bounds`  | ordered comparison keys compiled lexicographically |
| `count`   | `none` \| `exact` \| `estimated` |

Application is uniform and backend-agnostic:

```
q     = filter AND compile(bounds)
rows  = find(q).sort(sort).skip(skip).limit(limit)
total = count(filter) when count != none
```

`filter` is the existing scoping predicate (not a primitive); it ANDs into
`bounds`. Omitting every primitive yields the unbounded v0.2 list, byte for
byte.

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
| `since`/`until` | `bounds` on the range field (`gte`/`lt`) -- reserved |
| `cursor`    | decoded to `bounds` -- reserved |

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
tiebreaker and must be unique and indexed, otherwise the build fails. `after`
is an opaque base64url token encoding the previous page's sort position; the
service turns it into a compound lexicographic bound. Forward paging is stable
under concurrent inserts.

```yaml
pagination:
  strategy: keyset
  size: { default: 20, max: 100 }
  sort:
    - { field: score, dir: desc }
    - { field: id }          # unique tiebreaker
  envelope: true
```

### cursor / range (reserved)

`cursor`, `range`, and `count: estimated` are reserved vocabulary with no
runtime. A spec that declares one fails with `PAGINATION_UNSUPPORTED`.

## Envelopes

With `envelope: false` (the default) the response is a bare array -- the v0.2
shape. With `envelope: true`:

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
| `PAGINATION_INVALID_STRATEGY` | `strategy` is not a recognized value |
| `PAGINATION_UNSUPPORTED` | a reserved strategy or count mode has no runtime |
| `PAGINATION_INVALID_SIZE` | `size.default`/`size.max` missing, non-integer, or `default > max` |
| `PAGINATION_INVALID_COUNT` | `count` is not a recognized value |
| `PAGINATION_INVALID_OVERFLOW` | `onOverflow` is not `clamp`/`reject` |
| `PAGINATION_INVALID_SORT` | a sort entry is malformed |
| `PAGINATION_SORT_FIELD_UNKNOWN` | a sort field is not a field of the entity |
| `PAGINATION_KEYSET_SORT_REQUIRED` | keyset declared without a `sort` |
| `PAGINATION_KEYSET_TIEBREAKER_NOT_UNIQUE` | the last keyset sort field is not unique/indexed |
| `BACKEND_FEATURE_UNSUPPORTED` | a generated backend is asked to emit pagination |
