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

## v0.2 compatibility

v0.2 built-in single-record ops always use the `{id}` convention, so this
behavior is byte-identical there: the final (only) token is `id`, the record is
loaded by the id fetch, and a missing token yields the exact legacy message
`Missing route parameter: id`. The route-derived predicate is additive and
reachable only through v0.3 authoring (a freely-named or nested token); no v0.2
route, generated output, or error message changes.
