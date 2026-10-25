---
title: Access and binding grammar reference
description: Complete v0.3 reference for access values, given bindings, route slugs, where predicates, service inputs, forwarding, and rule bindings.
---

This page collects the access and binding forms accepted by a v0.3 spec. The
JSON schema validates their outer shape; the parsers and semantic validators
enforce the grammar, declared names, symbol scopes, and wiring rules described
below. The live server and generated FastAPI, Django REST Framework, and raw-ASGI
backends implement the same behavior.

## Access values

`access:` may be declared on a controller as the default for its routes or on an
individual route as a complete override.

```text
RoleRule ::= Entity ":" "*"
           | Entity ":" Role
           | Role
Access   ::= "public"
           | "*"
           | RoleRule
           | [ RoleRule | AccessRule, ... ]
```

| Value | Authentication and authorization |
| --- | --- |
| `public` | No principal is required. |
| `"*"` | Any authenticated principal. Quote it so YAML does not treat `*` as an alias. |
| `<entity>:*` | Any principal from the named `type: auth` entity. |
| `<entity>:<role>` | A principal from that auth entity holding the role. |
| `<role>` | The role on the only auth entity; rejected as ambiguous when multiple auth entities exist. |

A principal holds its own roles and every role they inherit through
`entities.<entity>.roles.hierarchy`, so with `editor: [viewer]` an editor passes
a `viewer` rule. A missing `access:` is
treated as public and emits the `PUBLIC_ROUTE` build warning. An explicit
`access: public` also emits a warning so accidental exposure is visible during
generation.

`authenticated` is not the any-authenticated spelling; use `"*"`.
Use `public` and `"*"` as complete access values, not as entries mixed into an
ordered rule list.

## Access-rule objects

An access list may contain rule objects:

```yaml
access:
  - given:
      principal: identity:user
      record: posts
    when: principal.sub equals record.ownerId
    then: allow
```

```text
AccessRule ::= {
  given?: GivenBindings,
  when?: WhenExpression | [WhenExpression, ...],
  then?: "allow" | "deny",
  reason?: String,
  bind?: SymbolBinding
}
```

At least one of `given`, `when`, or `then` is required, and any other key is
rejected with `SCHEMA_VALIDATION_ERROR`. `then` defaults to `allow`. Rules are
evaluated in order; the first matching rule decides the request. A matching deny
returns 403. When no rule matches, an anonymous caller gets 401 and a signed-in
one gets 403. A non-public route answers 401 to a request whose token or
password does not authenticate.

To require a role together with a condition, keep the role in an `enum` field
of the identity record named by `entities.<entity>.auth.roles` and test it in
`when:`, for example `principal.record.role in ['editor', 'admin']`.

`reason:` supplies the safe 403 detail; see
[Explainable access denials](access-reason.md). To fix the value of
a field a client must not choose, declare it `readonly: true` and supply it
through [`bind:`](#access-rule-bind).

### Row filtering on list routes

On a `list` route, a rule whose `when:` reads the bound collection becomes a row
filter: the datastore query returns only the rows the rule admits.

```yaml
operations:
  list:
    access:
      - admin
      - given:
          principal: identity:user
          document: sensitive_data
        when: principal.sub equals document.owner_id
```

An admin lists every row; any other signed-in user lists only their own.

## `given:` bindings

`given:` maps author-chosen symbol names to sources. `principal`, `document`,
and `request` are conventions, not built-in variable names.
`public` and `authenticated` are not bindings: declare public access with
`access: public` and any-authenticated access with `access: "*"`.

```text
GivenBindings   ::= { Name: GivenBinding, ... }
GivenBinding    ::= IdentityBinding
                  | DocumentBinding
                  | RequestBinding
                  | WhereBinding
IdentityBinding ::= "identity:" Entity
DocumentBinding ::= Collection [ " by " PathParameter ]
RequestBinding  ::= "request" [ "." RequestPart ] [ ":" Type ]
RequestPart     ::= "body" | "path" | "query" | "header" | "cookie"
```

| Form | Example | Bound value |
| --- | --- | --- |
| `identity:<entity>` | `principal: identity:user` | Authenticated principal, including `sub`, roles, identity collection, and stored record. |
| `<collection>` | `record: posts` | The route record from that collection. |
| `<collection> by <param>` | `owner: users by ownerId` | A record loaded by the named route parameter instead of the operation token. |
| `request` | `req: request` | Whole request; body remains raw. |
| `request:<type>` | `req: request:CreatePost` | Whole request with its body validated against a primitive, entity, or DTO. |
| `request.<part>` | `query: request.query` | One raw request part. |
| `request.<part>:<type>` | `body: request.body:CreatePost` | A typed body, path, or query part. |
| `<collection> where ...` | `owner: users where email = $req.body.email` | One record selected by an equality predicate. |

A type suffix is valid only for the whole request (where it types the body) or
for `body`, `path`, and `query`. Headers and cookies are not typeable. A body
binding is rejected on `get`, `list`, and `delete` because those operations do
not carry a body. Authentication runs before the body is read, so an anonymous
caller gets 401 whatever the body holds.

Every root used by `when:` must be a key in that same rule's `given:` map. Route
slugs are not ambient inside `when:`. Refer to
[When expressions](../v0.2/Reference/when-expressions/overview.md) for operand,
literal, and operator syntax.

## Route slugs and symbol scopes

A route declares a slug with braces and references its value with a `$` sigil:

```yaml
path: /organizations/{orgId}/posts/{postId}
```

Here `{orgId}` and `{postId}` declare the roots; `$orgId` and `$postId` reference
them. A `$` reference uses this shape:

```text
SymbolPath ::= "$" Name ( "." Name )*
Name       ::= ( letter | "_" ) ( letter | digit | "_" )*
```

There is no ambient `$principal`, `$request`, or `$document`. The available
roots depend on the reference site:

| Reference site | Ambient roots | Explicitly bound roots | Not available |
| --- | --- | --- | --- |
| `when:` operand | None | Every key in that rule's `given:` | Route slugs not also bound in `given:` |
| `where` right-hand side | Route slugs | Identity and request keys in the same rule's `given:` | Document and `where` result keys |
| Access-rule `bind:` value | Route slugs | Identity and request keys in the same rule's `given:` | Document and `where` result keys |
| Service `with:` value | None | Fields declared by that service's `input:` | Route, principal, request, and document roots |
| Repository operation query | Slugs on each route reaching the operation | Keys produced by the service's `with:` | Principal and request roots |

Repository-query validation is per route. If two routes reach one operation,
each route must independently supply every symbol used by that query.
`UNDEFINED_SYMBOL` aborts a v0.3 build whenever a root is absent from its site.
See [Symbol resolution](symbol-resolution.md) for examples.

## `where` bindings

A `where` binding selects one record before its access rule is evaluated:

```yaml
given:
  principal: identity:user
  category: assetCategories where slug = $categorySlug and active = true
```

```text
WhereBinding ::= Collection "where" Conjunct ( "and" Conjunct )*
Conjunct     ::= Field "=" Rhs
Rhs          ::= SymbolPath | String | Number | Boolean
Boolean      ::= "true" | "false"
```

`Collection` and `Field` are plain identifiers. A field is top-level and must
exist on the collection entity; dotted fields are rejected. Strings may use
single or double quotes and backslash escapes. Numbers accept an optional sign,
integers, decimals (including `.5` and `3.`), and exponents such as `1e3` or
`2.5E-2`. Keywords are lowercase and case-sensitive.

| Token | Status |
| --- | --- |
| `=` | Active comparison operator |
| `and` | Active conjunction |
| `!=`, `<`, `<=`, `>`, `>=`, `in` | Reserved and rejected with `WHERE_OPERATOR_UNSUPPORTED` |

Each rule receives its own fetched bindings, so equal symbol names in different
rules do not collide. A predicate miss makes only that rule fail; it never
returns 404. Evaluation continues, and the final result is the normal 401 or
403 if no rule allows the request. This prevents the route from revealing whether the
selected record exists. See [The `where` binding form](given-where.md) for the
complete parser and runtime contract.

## Service `input:` and `with:`

A service declares the request values it consumes and maps them into its
repository operation or handler:

```yaml
services:
  archivePost:
    repository: posts
    operation: archive
    input:
      postId: string
      reason:
        type: string
        required: false
    with:
      lookup: $postId
      state: archived
```

```text
InputConfig   ::= { Name: FieldType | FieldConfig, ... }
                | [ DtoName, ... ]
SymbolBinding ::= { Name: BindingValue, ... }
BindingValue  ::= SymbolPath | String | Number | Boolean
```

Both forms must be non-empty. A list in `input:` names DTOs whose fields are
merged; it is not a list of input field names. Inline inputs support `string`,
`number`, `boolean`, `datetime`, `enum`, `array`, `object`, and `ref`, including
their normal constraints. Inputs are required unless `required: false`.

Body fields and path parameters populate the input contract, with path values
taking precedence. `with:` right-hand symbols may reference only fields declared
by that service's `input:`. Its keys become the names available to a repository
query or handler. A repository forwarding key that its operation does not use is
rejected rather than silently discarded. See
[Service `input:` and `with:` forwarding](service-input.md).

## Access-rule `bind:`

An allow rule may supply trusted service inputs after it matches:

```yaml
access:
  - given:
      principal: identity:user
    bind:
      actorId: $principal.sub
```

`bind:` uses `SymbolBinding`. Each key must be declared in the route service's
`input:`. Route slugs and bind keys together must cover every required input.
The matching rule's values override client body and path values before input
validation, so the client cannot spoof them. Bindings on non-matching, deny, or
later rules are not applied.

A route using `bind:` cannot contain any document binding, including a `where`
binding, because service inputs are finalized before the document-authorization
lifecycle. Its expressions may use only route slugs and identity/request keys
from the same rule. See [Access-rule `bind:`](controller-bind.md).

## Single-record route locators

For v0.3 `get`, `update`, `replace`, and `delete` routes, the final route token
selects the record by the collection id field. Earlier tokens constrain fields
of the same name:

```text
/organizations/{orgId}/posts/{postId}
  -> posts where orgId = $orgId and id = $postId
```

Each earlier token must name a collection field. The full predicate is applied
atomically to reads and writes. See
[Freely-named single-record tokens](free-slug-fetch.md).

## Runtime results

| Status | Condition |
| --- | --- |
| 401 | A non-public route has no valid principal. |
| 403 | A signed-in caller meets an explicit deny, no allowing rule, or a `where` lookup miss. |
| 404 | An authorized single-record operation's route locator matches no target. |
| 409 | A datastore unique constraint rejects a write. |
| 422 | Request/service input validation fails, including a client value for a `readonly` field. |

The first matching rule decides access. Document-dependent rules run after the
route record is fetched; `where` bindings are isolated per rule. A v0.3 deny
reason and unique-conflict detail follow the security rules in
[Explainable access denials](access-reason.md) and
[Unique violations and `409 Conflict`](conflict-status.md).

## File endpoints

Derived [file endpoints](file-endpoints.md) declare no access of their own.
Download endpoints evaluate the access of the controller's `get` route, and
replace and delete endpoints evaluate the access of its `update` route, with
the same principal, `given:` bindings, `when:` rules and record locator. File
fields hold upload metadata, so they cannot be compared in `when:` or `where`.

## Coded diagnostics

### Access and `when:`

| Code | Condition |
| --- | --- |
| `ACCESS_UNKNOWN_ENTITY` | An identity or scoped-role form names an undeclared auth entity. |
| `ACCESS_NO_AUTH_ENTITY` | A bare role is used without any auth entity. |
| `ACCESS_AMBIGUOUS_ROLE` | A bare role is used with multiple auth entities. |
| `ACCESS_RULE_INVALID` | An access list/rule has an invalid shape or unsafe combination. |
| `WHEN_EXPR_INVALID` | A `when:` expression is empty or has trailing tokens. |
| `WHEN_OPERAND_MISSING` | An operator has no following operand. |
| `WHEN_OPERAND_INVALID` | An operand is not a field reference or supported literal. |
| `WHEN_LIST_INVALID` | An `in`/`not in` list is malformed. |
| `UNDEFINED_SYMBOL` | A `$` or `when:` root is absent from its exact v0.3 scope. |

`PUBLIC_ROUTE` is a warning, not a fatal error.

### `given:` and request bindings

| Code | Condition |
| --- | --- |
| `DOCUMENT_BINDING_INVALID` | A document binding is not `<collection>` or `<collection> by <param>`. |
| `REQUEST_BINDING_INVALID` | A request binding has an unknown part or includes a leaf in `given:`. |
| `REQUEST_TYPE_NOT_FOUND` | A request type is empty or not a primitive, entity, or DTO. |
| `REQUEST_TYPE_ON_LEAF` | A type is attached to a non-typeable request part. |
| `REQUEST_PATH_PARAM_NOT_DECLARED` | A request path field is not declared by the route template. |
| `REQUEST_BODY_ON_BODILESS_OP` | A body binding is used on `get`, `list`, or `delete`. |

### `where` and route locators

| Code | Condition |
| --- | --- |
| `WHERE_BINDING_INVALID` | The binding has invalid grammar, tokens, or a dotted field. |
| `WHERE_OPERATOR_UNSUPPORTED` | A reserved comparison operator is used. |
| `WHERE_RHS_INVALID` | A right-hand side is not a symbol, string, number, or boolean. |
| `WHERE_FIELD_UNKNOWN` | A predicate field is absent from the collection entity. |
| `ROUTE_LOCATOR_FIELD_UNKNOWN` | A parent route token is absent from the target collection entity. |
| `FILE_FIELD_NOT_COMPARABLE` | A `when:` operand or `where` predicate references a [file field](file-fields.md). |

### Service inputs, forwarding, and rule binding

| Code | Condition |
| --- | --- |
| `SERVICE_INPUT_INVALID` | `input:` is not a non-empty field map or DTO list. |
| `SERVICE_INPUT_FIELD_INVALID` | An inline input field type or `required` flag is invalid. |
| `SERVICE_INPUT_DTO_NOT_FOUND` | An `input:` list names an unknown DTO. |
| `SERVICE_WITH_VALUE_INVALID` | A `with:`/`bind:` value is not a `$` reference or scalar. |
| `SERVICE_WITH_TARGET_UNKNOWN` | A forwarding key is unused by its repository query. |
| `BIND_TARGET_UNKNOWN` | A bind key is not declared by the route service's input. |
| `BIND_MISSING_REQUIRED_INPUT` | Bind keys and route slugs do not cover a required input. |
| `BIND_DOCUMENT_RULE_UNSUPPORTED` | A bind-producing route also contains a document rule. |

## Version boundary

`where`, service `input:`/`with:`, access-rule `bind:`, unified
`UNDEFINED_SYMBOL`, token-derived record locators, pagination and file
endpoints are v0.3 only. A v0.2 spec binds identities, documents and requests,
fetches single records by `{id}`, and reports `WHEN_UNBOUND_SYMBOL` for an
unbound `when:` operand.
