---
title: v0.1 Documentation
description: Stackform v0.1 specification reference.
---

v0.1 documentation:

- [Specification](/docs/v0.1/specification) — YAML spec reference for v0.1
- [Structure](/docs/v0.1/structure) — project structure

The v0.1 dialect remains executable, not validation-only. `stackform run`
serves its routes under `api.basePath` and optional `api.version`, and
`stackform build` supports the FastAPI, Django REST Framework, and raw-ASGI
targets. The v0.1 specifications in `examples/valid/` are exercised against
all three generators in the compatibility test suite.
