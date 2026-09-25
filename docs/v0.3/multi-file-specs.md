---
title: Multi-file specs
description: Split a spec across files with `include`, and share YAML anchors across those files with `templates`.
---

## `include`: splitting a spec across files

A spec directory containing `api.yaml` may declare `include: [globs]`. Each
matched file is parsed as a YAML mapping and deep-merged into the manifest;
`api.yaml`'s own body (everything besides `include`/`templates`) merges last, as
an overlay. Patterns are resolved relative to the manifest and matched files are
processed in sorted order:

```yaml
# api.yaml
version: "0.3"
include: [domains/*.yaml]
```

```yaml
# domains/users.yaml
entities:
  user:
    fields:
      id: { type: id }
```

Two files may not define the same leaf key -- that raises `DUPLICATE_KEY`. Two
files defining sibling keys of the same object (`entities.user` in one file,
`entities.post` in another) merge cleanly.

## `templates`: sharing YAML anchors across files

`include` files are independent YAML documents, so a plain `&anchor` in one
file is invisible to a `*alias` in another -- PyYAML resets its anchor table at
the end of every document. `templates: [globs]` closes that gap: template
files are composed first, in listed/sorted order, purely to collect their
anchors into a pool shared by every `include` file and by `api.yaml`'s own
body. A template file's own data (any keys outside its anchors) is **not**
merged into the spec.

```yaml
# api.yaml
version: "0.3"
templates: [templates/*.yaml]
include: [domains/*.yaml]
```

```yaml
# templates/fields.yaml
_timestamps: &timestamps
  createdAt: { type: datetime }
  updatedAt: { type: datetime }
```

```yaml
# domains/posts.yaml
entities:
  post:
    fields:
      <<: *timestamps
      title: { type: string }
```

Both alias forms work across files:

- **Whole-value alias** -- `id: *idField` substitutes the anchored node as-is.
- **Merge key** -- `<<: *timestamps` merges the anchored mapping's keys into
  the surrounding mapping; keys declared locally (`title` above, or a field
  re-declared after the `<<:`) always win over the merged ones.

A later template file may alias an anchor defined by an earlier one (glob
order, then listed order). Anchors never leak sideways between `include`
files, or from an `include` file back into a template: each `include` file --
and `api.yaml`'s own body -- is parsed against the *same* template-only pool,
never against another `include` file's local anchors. Interpolation
(`${VAR}`) runs after the whole spec is merged, so it sees the fully aliased
and merged values, not raw anchor references.

## Errors

Both keys validate identically:

- `TEMPLATES_INVALID` / `INCLUDE_INVALID` -- the key is not a list of strings.
- `TEMPLATES_NO_MATCH` / `INCLUDE_NO_MATCH` -- a glob pattern matched no files.

Cross-file anchor resolution adds three codes. Each carries its precise
`<file>:<line>:<col>` in the error's `location` field (`path` stays `$`, since
these problems aren't tied to a merged spec key):

- `TEMPLATE_UNKNOWN` -- a `*alias` (or `<<: *alias`) has no matching anchor in
  the shared pool or earlier in the same file. The hint suggests the closest
  known anchor name, if one is close enough.
- `TEMPLATE_DUPLICATE` -- an anchor name is defined more than once: by two
  template files, or by an `include` file redefining a name the template pool
  already owns. Shadowing is not allowed -- rename one of the anchors.
- `TEMPLATE_CYCLE` -- an anchor references itself, directly or through the
  node it anchors (`&a [*a]`). Left unguarded this composes into a Python
  value that contains itself, which would recurse forever once `${VAR}`
  interpolation walks it; the loader rejects it at parse time instead.

## Editor and linter warnings

`templates/*.yaml` files are not valid standalone specs -- referenced from no
other file, they read as "defines an anchor, nothing else" -- and the
`include`/`domains/*.yaml` files that alias them use anchors your editor
cannot see. Expect two classes of false positives:

- **yamllint**: `anchors` rule warnings, or (with certain configs)
  `syntax-error` for an alias with no local anchor. Silence per-line with
  `# yamllint disable-line rule:anchors`, or disable the `anchors` rule for
  `include`/`templates` directories in `.yamllint`.
- **VS Code's YAML extension** (redhat.vscode-yaml): "Unresolved alias
  reference" (squiggly underline) on any cross-file `*alias`. This is a
  single-file limitation of the extension's YAML language server, not a build
  error -- `yaml-api build`/`run` resolve the alias correctly regardless. There
  is no per-line suppression for it; either ignore the warning for files under
  `templates:`/`include:` globs, or fold the shared block back into a single
  file (dropping `templates:`) where the anchor and alias stay in one
  document the language server can see.
