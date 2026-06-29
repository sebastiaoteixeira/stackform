---
title: "Access Policies"
description: Named, reusable when-fragments referenced as terms inside any access rule's when, composing with and/or/not.
---

A **policy** is a named, reusable `when:` fragment. You declare it once under a
top-level `policies:` block and reference it as a term inside any access rule's
`when:`, where it composes with `and`, `or`, and `not` like any other term.

> **Enforcement status**
>
> Policies are a pure build-time construct. Each `policy:<name>(...)` term is
> expanded into the referencing rule's `when:` AST before any backend is
> generated, so the resulting rule looks exactly as if you had written the
> expanded expression by hand. The generated FastAPI backend, the generated DRF
> backend, and the `yaml-api run` dev server need no policy-aware runtime: they
> evaluate the already-expanded rule. There is no new runtime primitive.

## Why policies exist

Before policies, the only way to reuse access logic was to repeat a rule across
the `access:` list. But the `access:` list is an OR: every rule you add only
**widens** access. There was no way to reuse a predicate that **narrows** access
-- to require a shared condition as one `and` term inside a single rule.

Policies close that gap. A policy is a reusable predicate that composes BOTH
ways:

- **OR across rules** -- the existing model. Each entry in an `access:` list is a
  separate rule; matching any one grants access.
- **AND / OR / NOT within a single `when:`** -- the new model. A `policy:<name>`
  term sits inside one rule's `when:` and combines with other terms, so reuse can
  now tighten access, not only widen it.

```yaml
access:
  - when: "policy:isTrustiantAdmin"                 # OR: admins always pass
  - given: { user: identity:user, target: risks }
    when: "policy:ownOrg(risks) and target.ownerId equals user.id"   # AND-tightened
```

The second rule reuses `ownOrg` and ANDs it with an extra term drawn from the
rule's own `given:`. The OR-splice model could not express that "reuse AND an
extra condition" shape -- splicing `ownOrg` as its own list entry would have
granted access on `ownOrg` alone.

## The `policies:` block

`policies:` is a top-level map of policy name to definition. Like other
top-level blocks, it is deep-merged across `include`d files.

```yaml
policies:
  isTrustiantAdmin:
    given: { user: identity:user }
    when: "'trustiant-admin' in user.roles"
  ownOrg:
    given: { user: identity:user }
    params: [target]
    when: "'org-admin' in user.roles and target.organizationId equals user.record.organizationId"
```

### Policy fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `given` | no | map of symbol to binding | Symbols the policy resolves itself. Same binding at every call site. Uses the existing `given` binding grammar (`identity:<entity>`, `request:<entity>`, `<collection>`, `<collection> by <param>`). |
| `params` | no | list of symbol names | Symbols the caller supplies positionally via `policy:name(arg1, arg2)`. Names only -- no binding here; the binding comes from the call site. |
| `when` | yes | string or list of strings | The reusable condition, parsed by the same parser as rule `when:`. List entries are ANDed. |

A policy name must match `^[a-zA-Z][a-zA-Z0-9_]*$`, or generation aborts with
`POLICY_NAME_INVALID`.

### No implicit symbols

Every root a policy's `when:` references MUST be declared in that policy's own
`given:` or `params:`. Anything else aborts generation with
`POLICY_UNBOUND_SYMBOL`. Rule symbols are NOT in scope inside the policy, and
policy symbols are NOT in scope in the rule. The only thing the call site
contributes is the param arg bindings inside `policy:name(...)`.

### Nesting

A policy `when:` MAY reference other policies as terms. The reference graph must
be acyclic; a cycle (`a` -> `b` -> `a`) aborts generation with `POLICY_CYCLE`.

## The `policy:<name>(args)` when-term

`policy:<name>(args)` is an atom in the `when:` grammar, alongside field
references, string literals, `in` expressions, and parenthesized groups. It
combines with `and`, `or`, `not`, and parentheses like any other term.

```
PolicyRef := "policy:" name ( "(" argList ")" )?
argList   := binding ("," binding)*
binding   := identity:<entity> | request:<entity> | <collection> | <collection> by <param>
```

- Arity must match: the number of args must equal the policy's `params` count, or
  generation aborts with `POLICY_ARITY_MISMATCH`. Args bind to `params`
  positionally; there are no keyword or defaulted args.
- A policy with no `params` is referenced **bare**, without parentheses:
  `policy:isTrustiantAdmin`. Supplying args to a no-params policy is a
  `POLICY_ARITY_MISMATCH`.
- A reference to an undefined policy aborts with `POLICY_NOT_FOUND`.

```yaml
when: "policy:isTrustiantAdmin"                      # bare, no params
when: "policy:ownOrg(request:riskCategory)"          # one positional arg
when: "policy:ownOrg(riskCategories)"                # arg is a fetched document
when: "policy:isTrustiantAdmin or policy:ownOrg(risks)"   # composed with or
```

## Param-arg record normalization

Each `params` entry is supplied positionally by the call-site binding, and the
binding KIND decides how the policy's `target.<field>` reads resolve. This is
what makes a single policy reusable across `create` (which has a body but no
fetched document) and `update`/`delete` (which have a fetched document):

| Arg binding | `target.<field>` reads | Notes |
|-------------|------------------------|-------|
| `request:<entity>` | the typed request **body** field, directly | `target.organizationId` reads `body.organizationId` -- not `target.body.organizationId`. The rule stays a **request rule**, so it remains valid on `create`. |
| `<collection>` (a document) | the **fetched document** field | Same semantics as a `given:` document binding -- the record is loaded first. |
| `identity:<entity>` | the **principal** | `target.sub`, `target.record.x`, `target.roles` keep principal semantics. |

The worked example below relies on exactly this: `ownOrg` uses
`target.organizationId` uniformly, yet `target` is the request body on `create`
and the fetched document on `update`/`delete`.

Because a `request:` arg keeps the policy a request rule (not a document rule),
a request-backed policy on `create` stays VALID -- it does not short-circuit the
way a document rule would.

## How expansion works

Policies introduce no runtime behavior. At IR-construction time, before any
backend projection:

1. Each `policies[*].when` is parsed once into a `when` AST.
2. When a rule's `when:` is compiled, each `policy:<name>(...)` term is replaced
   by the policy's AST:
   - nested policy references in the policy body are expanded first (depth-first,
     acyclic);
   - for each policy `given` entry and each `param`, a fresh unique symbol is
     minted (so it cannot collide with the rule's own symbols or with other
     policy references in the same rule), and its binding is added to the rule's
     symbol tables;
   - param symbols take their binding from the positional call-site arg, with the
     record normalization above applied;
   - the substituted policy AST is spliced into the rule's `when:`, parenthesized.
3. The fully-expanded AST is evaluated by the existing evaluator.

Document-dependence and pre-write timing are derived from the EXPANDED AST
exactly as for a hand-written rule: a `request:` symbol makes the rule a request
rule; a document symbol makes it a document rule. After expansion no
`policy:<name>` terms remain.

## Worked example

```yaml
policies:
  isTrustiantAdmin:
    given: { user: identity:user }
    when: "'trustiant-admin' in user.roles"
  ownOrg:
    given: { user: identity:user }
    params: [target]
    when: "'org-admin' in user.roles and target.organizationId equals user.record.organizationId"

controllers:
  riskCategories:
    service: riskCategories
    base_path: /risk-categories
    access: "*"
    operations:
      create:
        access:
          - when: "policy:isTrustiantAdmin"
          - when: "policy:ownOrg(request:riskCategory)"
      update:
        access:
          - when: "policy:isTrustiantAdmin"
          - when: "policy:ownOrg(riskCategories)"
  risks:
    service: risks
    base_path: /risks
    access: "*"
    operations:
      delete:
        access:
          - when: "policy:isTrustiantAdmin"
          - given: { user: identity:user, target: risks }
            when: "policy:ownOrg(risks) and target.ownerId equals user.id"
```

`ownOrg` is reused three ways with one definition:

- **`riskCategories.create`** -- `policy:ownOrg(request:riskCategory)` binds
  `target` to the submitted body. Because the arg is a `request:` binding, the
  rule stays a request rule and remains valid on `create`; `target.organizationId`
  reads `body.organizationId`.
- **`riskCategories.update`** -- `policy:ownOrg(riskCategories)` binds `target` to
  the fetched `riskCategories` record; `target.organizationId` reads the stored
  field.
- **`risks.delete`** -- `policy:ownOrg(risks) and target.ownerId equals user.id`
  reuses `ownOrg` AND tightens it with a term drawn from the rule's OWN `given:`
  (`user`, `target`). Note `target` here is the rule's own document symbol,
  independent of the policy's `target` param -- policy and rule symbols never
  share scope.

In each case `isTrustiantAdmin` is a separate OR rule: an admin passes
regardless of org.

## Errors

| Code | Condition |
|------|-----------|
| `POLICY_NOT_FOUND` | A `policy:<name>` term references a policy that is not defined. |
| `POLICY_CYCLE` | The policy reference graph contains a cycle (`a` -> `b` -> `a`). |
| `POLICY_PARSE_ERROR` | A policy's `when:` fails the parser (reported with the policy name). |
| `POLICY_UNBOUND_SYMBOL` | A policy's `when:` references a root not in that policy's `given` or `params`. |
| `POLICY_ARITY_MISMATCH` | A call-site arg count does not equal the policy's `params` count (including args on a no-params policy). |
| `POLICY_NAME_INVALID` | A policy name does not match `^[a-zA-Z][a-zA-Z0-9_]*$`. |

## See Also

- [When expressions](../when-expressions/overview.md)
- [When operators](../when-expressions/operators.md)
- [Access control](../controllers/access-control.md)
- [DTOs](../dto/overview.md)
