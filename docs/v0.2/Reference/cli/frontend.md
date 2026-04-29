---
title: "`yaml-api frontend`"
description: Generates a frontend application from a YAML API spec containing a `ui` block.
---

Generates a frontend application from a YAML API spec containing a `ui` block.

## Usage

```bash
yaml-api frontend <file.yaml> [options]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `<file.yaml>` | Path to the YAML spec file. Required. |

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output` | Overrides `ui.frontend.output` | Override the output directory for generated files. |
| `--schema` | auto-detected | Path to a custom JSON Schema for spec validation. Auto-detected from `version:` if omitted. |

## Requirements

The spec must contain a `ui:` block with at least the `frontend.pack` configuration. Example:

```yaml
ui:
  frontend:
    pack: react-query
    output: ./frontend/src
```

If the spec does not contain a `ui:` block, the command fails.

## Output

The command generates the files based on the specified resource pack. The generated output directory can be controlled by `ui.frontend.output` or the `--output` command-line option.
