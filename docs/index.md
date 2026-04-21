---
title: yaml-api-generator
description: A YAML-driven REST API engine that generates fully functional CRUD APIs backed by MongoDB. Write a declarative YAML spec, get a FastAPI server with authentication, authorization, and data validation -- zero hand-written server code.
---

A YAML-driven REST API engine that generates fully functional CRUD APIs backed by MongoDB. Write a declarative YAML spec, get a FastAPI server with authentication, authorization, and data validation -- zero hand-written server code.

yaml-api-generator is a local code generator you run on your own machine. You own the generated output and can deploy it anywhere. It is not a hosted backend-as-a-service (like Supabase or Firebase), and it is not a low-code admin panel. It produces standard Python (FastAPI) code that you can inspect, extend, and version-control.

## Architecture

```text
YAML Spec --> Parser --> Intermediate Representation --> Code Generator --> FastAPI + MongoDB
```

## Reading order

1. [Getting Started](./getting-started.md) -- install and run your first API
2. Tutorial (10 parts) -- build a complete API step by step
3. [Learn by Example](./LearnByExample/) -- full working projects
4. [Reference](./Reference/) -- detailed spec documentation

## Table of contents

### Getting Started

- [Getting Started](./getting-started.md)
- [Concepts](./concepts.md)

### Tutorial

1. [Hello World](./Tutorial/01-hello-world.md)
2. [Field Types](./Tutorial/02-field-types.md)
3. [Relationships](./Tutorial/03-relationships.md)
4. [Authentication](./Tutorial/04-authentication.md)
5. [Access Control](./Tutorial/05-access-control.md)
6. [Roles](./Tutorial/06-roles.md)
7. [ABAC Rules](./Tutorial/07-abac-rules.md)
8. [Entity Inheritance](./Tutorial/08-entity-inheritance.md)
9. [Custom Operations](./Tutorial/09-custom-operations.md)
10. [External Auth](./Tutorial/10-external-auth.md)

### Learn by Example

- [Blog](./LearnByExample/blog/01-overview.md)
- [Todo App](./LearnByExample/todo/01-overview.md)
- [Multi-tenant SaaS](./LearnByExample/multi-tenant-saas/01-overview.md)

### Reference

**CLI**
- [dev](./Reference/cli/dev.md)
- [compile](./Reference/cli/compile.md)

**Configuration**
- [api](./Reference/configuration/api.md)
- [mongo](./Reference/configuration/mongo.md)
- [Environment Variables](./Reference/configuration/environment-variables.md)

**Entities**
- [Overview](./Reference/entities/overview.md)
- [Field Types](./Reference/entities/field-types.md)
- [Primary Keys](./Reference/entities/primary-keys.md)
- [Inheritance](./Reference/entities/inheritance.md)

**Auth**
- [Overview](./Reference/auth/overview.md)
- [Password Provider](./Reference/auth/password-provider.md)
- [API Key Provider](./Reference/auth/apikey-provider.md)
- [Claim Mapping](./Reference/auth/claim-mapping.md)

**Providers**
- [Overview](./Reference/providers/overview.md)
- [OIDC](./Reference/providers/oidc.md)
- [SAML](./Reference/providers/saml.md)

**Repositories**
- [Overview](./Reference/repositories/overview.md)
- [Operations](./Reference/repositories/operations.md)

**Services**
- [Overview](./Reference/services/overview.md)
- [Custom Operations](./Reference/services/custom-operations.md)
- [Handler Context](./Reference/services/handler-context.md)

**Controllers**
- [Overview](./Reference/controllers/overview.md)
- [Operations](./Reference/controllers/operations.md)
- [Access Control](./Reference/controllers/access-control.md)

**Roles**
- [Overview](./Reference/roles/overview.md)
- [Hierarchy](./Reference/roles/hierarchy.md)

**When Expressions**
- [Overview](./Reference/when-expressions/overview.md)
- [Operators](./Reference/when-expressions/operators.md)

### Troubleshooting

- [Troubleshooting](./troubleshooting.md)

### Spec Documents

- [YAML Specification v0.1](./YAML-Specification-v0.1.md)
- [YAML Structure Spec v0.1](./YAML-Structure-Spec-v0.1.md)
