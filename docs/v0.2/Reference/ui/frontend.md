---
title: "Frontend Settings"
description: Configures generator rules and parameters for frontend generation.
---

The `ui.frontend` object holds meta-level configuration used by the `frontend` pipeline.

## Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pack` | string | **Required** | The name or path of the generator pack (e.g., `react-vite-tailwind`). |
| `output` | string | `./frontend/src` | Target output directory. |
| `overwrite` | string | `never` | File overwrite policy for editable zones. Usually `never` or `always`. |

### Pack Configuration

Any extra fields defined inside `ui.frontend` (except `pack`, `output`, `overwrite`, and `generate`) are considered **pack-specific configurations** and are passed through to the template rendering context.

```yaml
ui:
  frontend:
    pack: my-custom-pack
    output: ./out/ui
    overwrite: always
    theme_color: "#ff0000"  # Available in templates as context.pack_config.theme_color
```
