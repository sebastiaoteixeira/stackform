---
title: "When Expressions"
description: Conditional expressions evaluated against the authenticated principal and a fetched document inside ABAC access rules.
---

Conditional expressions evaluated against the authenticated principal and a fetched document inside ABAC access rules. A `when:` expression turns a static role/identity rule into an ownership or attribute check (for example, "the requester is the owner of this record").

> **Enforcement**
>
> Roles, role hierarchies, `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that no rule admits gets 401 when it
> carries no valid credentials and 403 otherwise; a missing record answers 404
> before ownership is checked.

## Syntax

`when:` appears inside an access-rule object. The rule's `given:` block binds the symbol names your expression references:

```yaml
api: { basePath: /api, version: v1 }   # routes are served under /api/v1/...

controllers:
  myCollection:
    access:
      - given:
          principal: identity:user
          document: myCollection
        when: principal.sub equals document.ownerId
```

`given:` is a map of symbol-name to binding. A binding is either:

- `identity:<entity>` -- binds the symbol to the authenticated principal of that auth entity.
- `<collection>` or `<collection> by <param>` -- binds the symbol to the route's document (the record being read or written), optionally looked up by a path parameter.

The symbol names are free-form. The example above uses `principal` and `document`, but you can name them anything:

```yaml
when:
  - given:
      requester: identity:user
      record: myCollection
    when: requester.sub equals record.ownerId
```

There are no built-in root symbols. Every root referenced in a `when:` expression
MUST be declared in that rule's `given:` block; an undeclared root aborts generation
with `WHEN_UNBOUND_SYMBOL`. `principal` and `document` are conventional names, not
keywords -- they only work because the examples bind them in `given:`. `batata` or
`orangotango` would work identically if you bound them.

### String form

```yaml
when: principal.sub equals document.ownerId
```

### List form (implicit AND)

```yaml
when:
  - principal.sub equals document.ownerId
  - document.status not equals 'archived'
```

A list of expressions is ANDed together. Equivalent to:

```yaml
when: principal.sub equals document.ownerId and document.status not equals 'archived'
```

## Evaluation

- **Parse time:** Expression strings are parsed into an expression tree. Invalid syntax aborts generation with a `WHEN_*` error (exit 1).
- **Runtime:** The expression is evaluated against the bound principal and document. It returns true or false, which combines with the rule's `then: allow|deny` effect.
- **When a document is involved:** Any rule whose `when` references a document symbol bound in `given:` is evaluated after the record is fetched. For `get`/`update`/`replace`/`delete`, the record is loaded first; a missing record returns 404 before the ownership check runs. `create` has no fetched document, so document-dependent rules do not apply to it.

## Field Paths

The paths below assume a `given:` that binds an identity to `principal` and a
collection to `document` (`given: { principal: identity:user, document: myCollection }`).
The names are the author's choice -- substitute whatever you declared in `given:`.

| Path | Description |
|------|-------------|
| `principal.sub` | The identity's primary-key value (string). |
| `principal.identity_collection` | The name of the identity's collection. |
| `principal.roles` | The identity's roles: the `auth.roles` field, or the managed `_auth.roles`. |
| `principal.record.fieldName` | Any field on the identity's stored record. Stored fields live under `record`, not directly on the symbol. |
| `document.fieldName` | A field on the fetched document the symbol is bound to. |

Field paths follow the symbol names you chose in `given:`. If you bind `requester: identity:user`, then write `requester.sub` and `requester.record.email`.

## The Request Source

Besides the principal and the route's document, a `given:` symbol can bind the
**incoming HTTP request**. This lets a `when:` rule read the request body, path
parameters, query string, headers, or cookies of the call being authorized. As
with every other root, there are no built-in request symbols: you declare a
symbol in `given:` and name it whatever you like.

The parts mirror the OpenAPI `in` parameter locations
(`path`, `query`, `header`, `cookie`), plus the request `body`:

| Part | Source | Shape | Typeable |
|------|--------|-------|----------|
| `body` | parsed JSON body | object | yes |
| `path` | path-template params (OpenAPI `in: path`) | `map<string,string>` | yes |
| `query` | query string (OpenAPI `in: query`) | `map<string,string\|string[]>` | yes |
| `header` | request headers, lowercased keys (OpenAPI `in: header`) | `map<string,string>` | no |
| `cookie` | request cookies (OpenAPI `in: cookie`) | `map<string,string>` | no |

### Binding forms

The value of a request binding in `given:` is a string. Four forms exist:

| Form | Binds | Body validation |
|------|-------|-----------------|
| `request` | the whole request | body left unchecked |
| `request:<type>` | the whole request | `.body` validated against `<type>` |
| `request.<part>` | one part, raw | none |
| `request.<part>:<type>` | one part (`body`/`query`/`path`) | validated against `<type>` |

`<part>` is one of `body`, `path`, `query`, `header`, `cookie`. `<type>` is a
primitive (`string`, `number`, `boolean`, `datetime`), an entity name, or a DTO
name (see [DTOs](../dto/overview.md)).

```yaml
given:
  req: request                          # whole request, body unchecked
  req: request:createMembership         # whole request, .body validated as a DTO
  member: request.body                  # just the body, raw
  member: request.body:createMembership # just the body, validated
  page: request.query                   # the query-string map, raw
  org: request.path                     # the path-param map, raw
```

The symbol name is arbitrary — `req`, `member`, `org` above are the author's
choice, exactly like `principal` and `document`.

### Reading parts in `when:`

A symbol bound to the whole request (`request` or `request:<type>`) is
**part-qualified**: you name the part, then the key.

```yaml
when: req.body.role equals 'admin'
when: req.path.orgId equals principal.record.orgId
when: req.query.scope equals 'all'
when: req.header.authorization not equals ''
when: req.cookie.session not equals ''
```

A symbol bound to one part holds that part, so you name the key directly:
`member.role` for `member: request.body`, `org.orgId` for `org: request.path`.

The binding value in `given:` is only the binding itself (`request`,
`request.body`, `request:createMembership`). Part-qualified leaf access such as
`req.body.role` lives in `when:`, never in `given:`. Writing `request.body.role`
as a `given:` value is rejected with `REQUEST_BINDING_INVALID`.

### Typing rules

`:<type>` is legal only on object-shaped targets: after `request:` (which types
the body), and on `request.body`, `request.query`, `request.path`. It is
rejected on a single leaf and on `header` or `cookie` (which are not typeable),
failing generation with `REQUEST_TYPE_ON_LEAF`.

A path parameter read in `when:` (`req.path.<name>`, or `org.<name>` for
`org: request.path`) must name a `{name}` present in that route's composed path
template (the existing `{id}` of CRUD routes, or an explicit route such as
`/{orgId}/members`). An undeclared name fails with
`REQUEST_PATH_PARAM_NOT_DECLARED`.

### Runtime model

Request resolution is fail-safe: a missing leaf resolves to `null`, it never
raises. `req.body.x` where the body has no `x` is `null`, the same as a missing
principal or document field.

A typed body is validated against the bound DTO or entity: a request the rules
admit whose body does not match returns 422. The
parts are sourced as follows: `body` from the parsed JSON body, `path` from the
route's URL parameters, `query` from the query string, `header` from the request
headers (lowercased keys), and `cookie` from the request cookies.

### Applicability

`body` (and `request:<type>`) is only meaningful on operations that carry a body:
`create`, `update`, `replace`. Using a body binding on a bodiless operation
(`get`, `list`, `delete`) fails with `REQUEST_BODY_ON_BODILESS_OP`. The other
parts (`path`, `query`, `header`, `cookie`) apply to every operation.

This is the key gap it closes for `create`: a create has no fetched document, so
document rules never run for it. A request binding lets a create rule reason
about the very payload being submitted — for example, "a non-admin may not
create a membership with `role: admin`".

## Operands and Literals

Operands are either field references (as above) or single-quoted string literals:

- **String literals:** Single quotes only: `'admin'`, `'active'`. Double quotes are not supported and cause a parse error.
- **List literals:** `['admin', 'moderator']` for use with `in` / `not in`.

There are no numeric or boolean literals. Compare against single-quoted strings instead (for example, `document.status equals 'published'`, not `document.published equals true`).

## Operators

See [operators](./operators.md) for the complete reference.

| Operator | Example |
|----------|---------|
| `equals` | `principal.sub equals document.ownerId` |
| `not equals` | `document.status not equals 'archived'` |
| `in` | `principal.record.role in ['admin', 'moderator']` |
| `not in` | `document.status not in ['deleted', 'archived']` |
| `and` | `A and B` |
| `or` | `A or B` |
| `not` | `not A` |

Use the operator words; `==` and `!=` are not recognized. Operator and keyword matching is case-insensitive, so `equals`, `Equals`, and `EQUALS` are all accepted (lowercase is the convention used throughout these docs).

## Examples

```yaml
when: principal.sub equals document.ownerId
when: principal.record.role equals 'admin'
when: principal.record.role in ['admin', 'moderator']
when: document.status not in ['deleted', 'archived']
when: principal.sub equals document.ownerId and document.status equals 'active'
when: not document.locked
```

### Allow owner or role

```yaml
api: { basePath: /api, version: v1 }

controllers:
  myCollection:
    access:
      - moderator
      - given:
          principal: identity:user
          document: myCollection
        when: principal.sub equals document.ownerId
```

The bare-role rule is checked first (no document load). If it does not match, the ownership rule loads the record and allows the owner.

### Deny non-owners, allow everyone else

```yaml
api: { basePath: /api, version: v1 }

controllers:
  myCollection:
    access:
      - given:
          principal: identity:user
          document: myCollection
        when: principal.sub not equals document.ownerId
        then: deny
      - then: allow
```

Non-owners are denied. The owner falls through to the trailing `then: allow`.

## Edge Cases

- **Missing principal field.** `principal.record.X` where `X` does not exist resolves to `null`. `null equals null` is true; `null equals 'anything'` is false.

- **Missing document field.** `document.X` where `X` does not exist resolves to `null`.

- **Precedence.** `not` binds tightest, then `and`, then `or`. So `A or B and C` means `A or (B and C)`. Parentheses override it: `(A or B) and C`.

- **`principal.sub` type.** Always a string (the principal's primary-key value, stringified).

- **`in []` (empty list).** Always false. **`not in []`** is always true.

- **String literals must be single-quoted.** `'admin'` is valid; `"admin"` is a parse error.

- **List syntax `when: [expr1, expr2]`.** ANDs the expressions together, equivalent to `when: "expr1 and expr2"`.

## Errors

| Code | Condition |
|------|-----------|
| `WHEN_EXPR_INVALID` | Empty expression or an unexpected token after a complete expression. |
| `WHEN_OPERAND_MISSING` | An operator with no following operand. |
| `WHEN_OPERAND_INVALID` | An operand that is neither a field reference nor a single-quoted string. |
| `WHEN_LIST_INVALID` | A malformed `[...]` list for `in` / `not in`. |
| `WHEN_UNBOUND_SYMBOL` | A `when:` references a root symbol not declared in the rule's `given:`. |
| `DOCUMENT_BINDING_INVALID` | A `given:` document binding that is not `<collection>` or `<collection> by <param>`. |
| `ACCESS_UNKNOWN_ENTITY` | A `given:` `identity:<entity>` naming an entity that is not a `type: auth` entity. |
| `REQUEST_BINDING_INVALID` | A `request*` binding value that is unknown, multi-segment, or carries part-qualified leaf access (for example `request.body.x` in `given:`). |
| `REQUEST_TYPE_NOT_FOUND` | A request binding `:<type>` that is not a primitive, entity, or DTO. |
| `REQUEST_TYPE_ON_LEAF` | A `:<type>` on a leaf, or on `header`/`cookie` (not typeable). |
| `REQUEST_PATH_PARAM_NOT_DECLARED` | `request.path.<name>` where `<name>` is not a `{name}` in the route's path template. |
| `REQUEST_BODY_ON_BODILESS_OP` | A `request.body` / `request:<type>` binding on `get`, `list`, or `delete`. |

## See Also

- [Operators](./operators.md)
- [DTOs](../dto/overview.md)
- [Access control](../controllers/access-control.md)
