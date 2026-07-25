# Vendored imports

Under `version: "0.3"` an `imports` entry is an **object** that vendors a custom
handler package into the generated backend. The source directory is copied whole
into `target/<package>/`, the emitted code imports the vendored package name, and
the declared dependencies are merged into the target manifest.

```yaml
version: "0.3"
imports:
  handlers:
    path: ./src/handlers
    package: app_handlers
    requires: ["httpx>=0.27"]
```

- `path` — directory copied whole into `target/<package>/` (local helper modules
  travel with it, so a handler may import same-directory siblings).
- `package` — the package name the generated code imports.
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

## Multiple packages and shared code

Each entry vendors exactly one package, independently. Code shared between two
handler packages must be its own `imports` entry and imported through its own
package name — it is never duplicated into both targets.

## Dependency merging

`requires` from every entry are unioned into the manifest. When several entries
constrain the same library, their specifiers are intersected; an empty
intersection is a build error.

## Version gate

- **v0.2** is untouched: an `imports` entry is a bare dotted string that is
  imported (not vendored), and repository-operation handlers stay verbatim.
- **v0.3** requires the object form. A bare-string `imports` entry is rejected;
  there is no back-compatibility shim.

## Build errors

| Code | Cause |
| --- | --- |
| `IMPORT_BARE_STRING` | A v0.3 `imports` entry uses the bare dotted-string form instead of the vendored object. |
| `IMPORT_INVALID` | A v0.3 `imports` entry is missing `path` or `package`. |
| `IMPORT_PACKAGE_COLLISION` | Two entries vendor the same `package` name. |
| `IMPORT_UNDECLARED_PACKAGE` | A handler references a package that no `imports` entry vendors. |
| `IMPORT_REQUIRES_CONFLICT` | Requirements for one library are jointly unsatisfiable. |
