---
title: v0.3 Documentation
description: Spec version 0.3 adds multi-file specs, a richer access-rule grammar, service input contracts, MongoDB migrations, and OIDC hardening.
---

Spec version 0.3 builds on [v0.2](/docs/v0.2). A spec opts in with
`version: 0.3`; v0.2 specs keep working unchanged.

## Spec structure

- [Spec version 0.3](/docs/v0.3/spec-version) — what `version: 0.3` enables and how it is selected
- [Multi-file specs](/docs/v0.3/multi-file-specs) — splitting one application across several YAML files
- [Symbol resolution](/docs/v0.3/symbol-resolution) — how names are resolved across files
- [Vendored imports](/docs/v0.3/vendored-imports) — copying custom-handler packages into the generated target

## Access rules and binding

- [Access and binding grammar reference](/docs/v0.3/grammar-reference) — the complete rule grammar
- [Access-rule `role:`](/docs/v0.3/access-role) — requiring a role on the long rule form
- [Access-rule `bind:`](/docs/v0.3/controller-bind) — supplying trusted service inputs from a rule
- [The `where` binding form](/docs/v0.3/given-where) — deriving repository filters from the principal
- [Explainable access denials](/docs/v0.3/access-reason) — attaching a reason to a deny rule
- [The removed access-rule `filter` key](/docs/v0.3/removed-filter-key)
- [The removed access-rule `writeFields` key](/docs/v0.3/removed-write-fields-key)

## Services and data

- [Service `input:` and `with:` forwarding](/docs/v0.3/service-input) — declaring and mapping service inputs
- [Pagination](/docs/v0.3/pagination) — paged list responses
- [Freely-named single-record tokens](/docs/v0.3/free-slug-fetch) — fetching one record by an arbitrary field
- [Unique violations and `409 Conflict`](/docs/v0.3/conflict-status) — mapping unique constraints to a status
- [MongoDB migrations](/docs/v0.3/mongo-migrations) — revision ledger, autogeneration, and baseline stamping

## Authentication

- [RS256 session tokens](/docs/v0.3/rs256-signing) — asymmetric session signing
- [Refresh-token rotation](/docs/v0.3/refresh-tokens) — short-lived access tokens with rotating refresh tokens
- [Cookie (BFF) session delivery](/docs/v0.3/cookie-bff) — HttpOnly cookie sessions
- [Dual-trust token dispatch](/docs/v0.3/trust-dispatch) — `trust: app` and `trust: idp` side by side
- [Resource-server IdP token verification](/docs/v0.3/verify-idp) — verifying IdP tokens directly
- [PKCE for the OIDC client](/docs/v0.3/pkce) — RFC 7636 authorization-code binding
- [DPoP for the OIDC client](/docs/v0.3/dpop) — RFC 9449 sender-constrained tokens

## Deployment

- [Deploy](/docs/v0.3/deploy) — backend packages and processes, a hand-written frontend, registries and environments
