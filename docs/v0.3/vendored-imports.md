---
title: Vendored imports
description: Copy custom-handler packages and their dependencies into the generated target under v0.3.
---

Under `version: "0.3"` an `imports` entry may be an **object** that vendors a
custom handler package into the generated backend. The source directory is
copied whole into `backend/<package>/`, the emitted code imports the vendored
package name, and the declared dependencies are merged into the target manifest,
so the generated target no longer needs the author's package to be installed.

```yaml
version: "0.3"
imports:
  handlers:
    path: ./src/handlers
    package: app_handlers
    requires: ["httpx>=0.27"]
```

- `path` — a directory inside the spec's own directory, copied whole into
  `backend/<package>/` (local helper modules travel with it, so a handler may
  import same-directory siblings). It must be a regular package, that is, it must
  contain an `__init__.py`.
- `package` — the package name the generated code imports. It must be a Python
  identifier and must not collide with a module the backend generator emits.
- `requires` — optional dependency specifiers merged into `requirements.txt`.

Call sites are unchanged: a handler still reads `handler: handlers.publish`. The
alias (`handlers`) resolves to the vendored `package`, so the generated backend
emits `import app_handlers` / `await app_handlers.publish(**kwargs)` — never the
author-side dotted path.

```yaml
repositories:
  posts:
    entity: post
    operations:
      publish: { handler: handlers.publish }
```

## Where vendoring applies

Vendoring happens in the compiler, after the backend is generated and before the
output is complete, so it applies identically to the `fastapi`, `drf` and `raw`
targets: each receives `backend/<package>/` and the merged `requirements.txt`.
Both the repository-operation handler form and the service handler form resolve
to the vendored package in all three.

`yaml-api run` serves the spec in place and never writes a target, so it binds
each declared `package` name to its source directory through an import finder.
A vendored handler therefore resolves under the development server exactly as it
does in a generated target.

## Multiple packages and shared code

Each entry vendors exactly one package, independently. Code shared between two
handler packages must be its own `imports` entry and imported through its own
package name — it is never duplicated into both targets.

Isolation between packages is out of scope: the target is a single merged
environment, so two packages cannot depend on incompatible versions of the same
library.

## Dependency merging

`requires` from every entry are unioned into the manifest, grouped per library
and per environment marker. Extras are unioned, direct URLs are carried through,
and specifiers are conjoined. A conflict is reported only where it is decidable:
a group that pins exact versions none of its own constraints admit, and a library
constrained by both a direct URL and a version. Every other group is emitted as
the conjunction of the declared specifiers and left to the target installer.

## Safety

The source is resolved against the directory holding the spec and must stay
inside it, so an absolute path or one escaping through `..` is rejected rather
than read. A symlink inside the tree whose target leaves the tree is rejected,
and the copy preserves symlinks instead of following them, so no content from
outside the vendored tree is ever materialised into the target. A vendored
package may not take the name of a generated module, and copies left by an
earlier build of the same spec are cleared before generation, so rebuilding into
one output directory neither shadows generated code nor keeps deleted files.

## Version gate

- **v0.2** is untouched: an `imports` entry is a bare dotted string that is
  imported (not vendored), and repository-operation handlers stay verbatim.
- **v0.3 without an `imports` block** keeps the same handler semantics: a dotted
  handler is emitted verbatim and imported from the target environment.
- **v0.3 with an `imports` block** requires the object form and opts the whole
  spec into vendoring: every handler must name a vendored package, and a
  bare-string entry is rejected. There is no back-compatibility shim.

## Build errors

| Code | Cause |
| --- | --- |
| `IMPORT_BARE_STRING` | A v0.3 `imports` entry uses the bare dotted-string form instead of the vendored object. |
| `IMPORT_PACKAGE_COLLISION` | Two entries vendor the same `package` name. |
| `IMPORT_SOURCE_OUTSIDE_SPEC` | An entry's `path` resolves outside the directory holding the spec. |
| `IMPORT_SOURCE_MISSING` | An entry's `path` is not an existing directory. |
| `IMPORT_SOURCE_NOT_PACKAGE` | An entry's `path` has no `__init__.py`. |
| `IMPORT_SOURCE_ESCAPING_SYMLINK` | The vendored tree contains a symlink pointing outside it. |
| `IMPORT_PACKAGE_SHADOWS_TARGET` | A vendored `package` name is already occupied by a generated module. |
| `IMPORT_UNDECLARED_PACKAGE` | A handler references a package that no `imports` entry vendors. |
| `IMPORT_REQUIRES_INVALID` | A `requires` entry is not a valid dependency specifier. |
| `IMPORT_REQUIRES_CONFLICT` | Requirements for one library cannot be merged into one specifier. |
