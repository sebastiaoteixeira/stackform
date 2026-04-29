---
title: "UI Generation Overview"
description: Defines frontend user interfaces directly in the YAML spec.
---

The `ui:` block allows you to specify the frontend structure for your application alongside the backend configuration. The YAML API generator can then automatically scaffold and generate frontend projects based on the configured pack.

## Concepts

The `ui:` definition follows a layered architecture:

- **Frontend Settings (`ui.frontend`):** Defines global configurations such as which generator pack to use (e.g., `react-query`) and where to output files.
- **Collections (`ui.collections`):** Defines data tables mapping API entities to flattened, formatable frontend models.
- **Components (`ui.components`):** Reusable UI building blocks declaring their `props` and nested structural `render` components.
- **Views (`ui.views`):** Page-level routes that compose components and collections together.

## Basic Structure

```yaml
ui:
  frontend:
    pack: "react-vite-tailwind"
    output: "./frontend/src"
    overwrite: "never"
  
  collections:
    # Formatted presentation data
  
  components:
    # Reusable UI parts
    
  views:
    # Pages and routing
```

## Generation

Run the `frontend` CLI command to generate the UI project:

```bash
yaml-api frontend myapp.yaml
```

The `compile` command also processes the `ui:` block automatically if it is present, outputting generated files to `<output>/frontend`.

```bash
yaml-api compile myapp.yaml
```
