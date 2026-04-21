---
title: "Multi-Tenant SaaS: Full Spec"
---

# Multi-Tenant SaaS: Full Spec

```yaml
version: "0.2"

mongo:
  uri: ${MONGO_URI:-mongodb://localhost:27017}
  database: ${MONGO_DB:-saas}

entities:
  base:
    abstract: true
    fields:
      id: { type: id }
      createdAt: { type: datetime }

  # Human users -- password auth with org-scoped roles stored on membership
  user:
    extends: base
    type: auth
    auth:
      identifier: email
      via: password
    fields:
      email: { type: string, required: true, unique: true }
      displayName: { type: string, required: true }

  # Machine-to-machine clients -- API key auth with tier-based roles
  apiClient:
    extends: base
    type: auth
    auth:
      identifier: clientId
      via: apiKey
    roles:
      values: [free, premium, enterprise]
      default: free
      hierarchy:
        enterprise: [premium]
        premium: [free]
    fields:
      clientId: { type: string, required: true, unique: true }
      name: { type: string, required: true }

  org:
    extends: base
    fields:
      name: { type: string, required: true }
      slug: { type: string, required: true, unique: true }

  # Join table: user + org + role in that org
  membership:
    extends: base
    fields:
      userId: { type: ref, ref: user, required: true }
      orgId: { type: ref, ref: org, required: true }
      role:
        type: enum
        values: [owner, admin, member]
        default: member

  resource:
    extends: base
    fields:
      name: { type: string, required: true }
      orgId: { type: ref, ref: org, required: true }
      data: { type: object }

repositories:
  users:
    entity: user
  apiClients:
    entity: apiClient
  orgs:
    entity: org
  memberships:
    entity: membership
  resources:
    entity: resource

services:
  users: {}
  apiClients: {}
  orgs: {}
  memberships: {}
  resources: {}

controllers:
  users:
    service: users
    base_path: /users
    operations:
      register: { access: public }
      login: { access: public }

  apiClients:
    service: apiClients
    base_path: /api-clients
    access: "[user:*, apiClient:enterprise]"
    operations:
      create: { access: "user:*" }

  orgs:
    service: orgs
    base_path: /orgs
    access: "[user:*, apiClient:*]"
    operations:
      create: { access: "user:*" }
      update:
        access:
          - given:
              principal: identity:user
              document: memberships
            when: principal.sub equals document.userId and document.role equals 'owner'
      delete:
        access:
          - given:
              principal: identity:user
              document: memberships
            when: principal.sub equals document.userId and document.role equals 'owner'

  memberships:
    service: memberships
    base_path: /memberships
    access: "user:*"
    operations:
      delete:
        access:
          - given:
              principal: identity:user
              document: memberships
            when: principal.sub equals document.userId

  resources:
    service: resources
    base_path: /resources
    access: "[user:*, apiClient:*]"
    operations:
      create: { access: "[user:*, apiClient:*]" }
      update: { access: "apiClient:enterprise" }
      delete:
        access:
          - given:
              principal: identity:user
              document: resources
            when: principal.sub equals document.orgId
```

## Notes on this spec

**Two auth entities require scoped access rules.** `user:*` and `apiClient:*` are mandatory. Writing just `*` means any authenticated principal regardless of entity type.

**No global user roles.** User roles are org-scoped and live on the `membership` entity. ABAC rules check `document.role` on the membership record, not `principal.record.role`.

**apiClient tier hierarchy.** `enterprise: [premium]` means an enterprise client satisfies `access: apiClient:premium` checks. This allows tiered API access gating.

**`[user:*, apiClient:*]` syntax.** When access must allow multiple entity types, use a YAML list or the inline bracket form. Both are equivalent:

```yaml
access: "[user:*, apiClient:*]"
# same as:
access:
  - user:*
  - apiClient:*
```
