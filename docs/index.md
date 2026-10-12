---
title: Stackform
description: A YAML-driven REST API engine that generates fully functional CRUD APIs backed by MongoDB. Write a declarative YAML spec, get a FastAPI server with authentication, authorization, and data validation -- zero hand-written server code.
---

A YAML-driven REST API engine that generates fully functional CRUD APIs backed by MongoDB. Write a declarative YAML spec, get a FastAPI server with authentication, authorization, and data validation -- zero hand-written server code.

Stackform is a local code generator you run on your own machine. You own the generated output and can deploy it anywhere. It is not a hosted backend-as-a-service (like Supabase or Firebase), and it is not a low-code admin panel. It produces standard Python (FastAPI) code that you can inspect, extend, and version-control.

## Architecture

```text
YAML Spec --> Parser --> Intermediate Representation --> Code Generator --> FastAPI + MongoDB
```

## Reading order

1. [Getting Started](./v0.2/getting-started) -- install and run your first API
2. [Concepts](./v0.2/concepts) -- core concepts
3. Tutorial (10 parts) -- build a complete API step by step
4. [Learn by Example](./v0.2/LearnByExample/) -- full working projects
5. [Reference](./v0.2/Reference/) -- detailed spec documentation

## Table of contents

### Getting Started

- [Getting Started](./v0.2/getting-started)
- [Concepts](./v0.2/concepts)

### Tutorial

1. [Hello World](./v0.2/Tutorial/01-hello-world)
2. [Field Types](./v0.2/Tutorial/02-field-types)
3. [Relationships](./v0.2/Tutorial/03-relationships)
4. [Authentication](./v0.2/Tutorial/04-authentication)
5. [Access Control](./v0.2/Tutorial/05-access-control)
6. [Roles](./v0.2/Tutorial/06-roles)
7. [ABAC Rules](./v0.2/Tutorial/07-abac-rules)
8. [Entity Inheritance](./v0.2/Tutorial/08-entity-inheritance)
9. [Custom Operations](./v0.2/Tutorial/09-custom-operations)
10. [External Auth](./v0.2/Tutorial/10-external-auth)

### Learn by Example

- [Blog](./v0.2/LearnByExample/blog/01-overview)
- [Todo App](./v0.2/LearnByExample/todo/01-overview)
- [Multi-tenant SaaS](./v0.2/LearnByExample/multi-tenant-saas/01-overview)

### Reference

**CLI**
- [dev](./v0.2/Reference/cli/dev)
- [compile](./v0.2/Reference/cli/compile)

**Configuration**
- [api](./v0.2/Reference/configuration/api)
- [mongo](./v0.2/Reference/configuration/mongo)
- [Environment Variables](./v0.2/Reference/configuration/environment-variables)

**Entities**
- [Overview](./v0.2/Reference/entities/overview)
- [Field Types](./v0.2/Reference/entities/field-types)
- [Primary Keys](./v0.2/Reference/entities/primary-keys)
- [Inheritance](./v0.2/Reference/entities/inheritance)

**Auth**
- [Overview](./v0.2/Reference/auth/overview)
- [Password Provider](./v0.2/Reference/auth/password-provider)
- [API Key Provider](./v0.2/Reference/auth/apikey-provider)
- [Claim Mapping](./v0.2/Reference/auth/claim-mapping)

**Providers**
- [Overview](./v0.2/Reference/providers/overview)
- [OIDC](./v0.2/Reference/providers/oidc)
- [SAML](./v0.2/Reference/providers/saml)

**Repositories**
- [Overview](./v0.2/Reference/repositories/overview)
- [Operations](./v0.2/Reference/repositories/operations)

**Services**
- [Overview](./v0.2/Reference/services/overview)
- [Custom Operations](./v0.2/Reference/services/custom-operations)
- [Handler Context](./v0.2/Reference/services/handler-context)

**Controllers**
- [Overview](./v0.2/Reference/controllers/overview)
- [Operations](./v0.2/Reference/controllers/operations)
- [Access Control](./v0.2/Reference/controllers/access-control)

**Roles**
- [Overview](./v0.2/Reference/roles/overview)
- [Hierarchy](./v0.2/Reference/roles/hierarchy)

**When Expressions**
- [Overview](./v0.2/Reference/when-expressions/overview)
- [Operators](./v0.2/Reference/when-expressions/operators)

### Troubleshooting

- [Troubleshooting](./v0.2/troubleshooting)

### Spec Documents

- [YAML Specification v0.1](./YAML-Specification-v0.1.md)
- [YAML Structure Spec v0.1](./YAML-Structure-Spec-v0.1.md)
