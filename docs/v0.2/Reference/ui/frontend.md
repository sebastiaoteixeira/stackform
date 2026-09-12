---
title: "Frontend Settings"
description: Configures the UI pack, theming, and output policy for the generated React frontend.
---

The `ui.frontend` block selects the generator pack and controls how the React
frontend is written. The sibling `ui.config` block carries theming and the
login-gate toggle. Together they produce a Vite + React + TypeScript + Tailwind
project that talks to your generated backend.

A frontend is emitted only when the spec has a `ui:` block and you build the
frontend target:

```bash
yaml-api build myapp.yaml frontend   # frontend only
yaml-api build myapp.yaml all        # backend + frontend + deploy
```

## ui.frontend options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pack` | string | **Required** | The generator pack to use. The only built-in pack is `generic`. |
| `output` | string | (not consumed) | Present for forward compatibility; the build CLI does NOT read this field. See [Output location](#output-location). |
| `overwrite` | string | `never` | Overwrite policy for editable files: `never` or `always`. See [Overwrite policy](#overwrite-policy). |

```yaml
api:
  basePath: /api
  version: v1

ui:
  frontend:
    pack: generic
    overwrite: always
  config:
    app_name: My App
```

If `pack` is missing or blank, `yaml-api build <file> frontend` exits 1 with
`Error: ui.frontend.pack is required.`. If the spec has no `ui:` block at all,
`yaml-api build <file> frontend` exits 1 with
`Error: No 'ui' block found in the YAML spec.`. (During `yaml-api build <file> all`
a missing `ui:` block is simply skipped rather than an error.)

### Output location

- `yaml-api build <file> all -o ./target` writes the frontend to `./target/frontend`.
- `yaml-api build <file> frontend -o ./web` writes to `./web`.
- Without `-o`, a frontend-only build uses `ui.frontend.output`; if that is
  absent it writes to `./frontend`.

Inside the output directory the pack lays out:

- `src/__generated__/` -- regenerated every build (types, API client, hooks); do
  not edit by hand.
- `src/pages/`, `src/components/` -- editable application code, governed by
  `overwrite`.
- Root project files (`package.json`, `vite.config.ts`, `tsconfig.json`,
  `tailwind.config.js`, `index.html`, and so on).

### Overwrite policy

Generated files in `src/__generated__/` are always rewritten on every build.
The `overwrite` field only affects editable files (pages and components):

- `never` (default): an editable file is written only if it does not already
  exist, so your hand edits survive subsequent builds.
- `always`: editable files are rewritten every build, discarding local changes.

## ui.config (theming and app shell)

Any keys under `ui.config` are merged into the pack configuration and exposed to
the pack templates as `pack_config.<key>`. The `generic` pack reads:

| Key | Type | Description |
|-----|------|-------------|
| `app_name` | string | Brand name shown in the sidebar, page title, and auth screen. |
| `require_auth` | boolean | When true (default), the app is wrapped in a login gate. Set false for a public app. |
| `fonts` | object | UI/title/mono font families and Google Fonts import flags. |
| `colors` | object | Light-theme color tokens (any valid CSS color, e.g. `oklch(...)`). |
| `colors_dark` | object | Dark-theme overrides for the same tokens. |

```yaml
ui:
  frontend:
    pack: generic
    overwrite: always
  config:
    app_name: My App
    require_auth: false
    fonts:
      ui: IBM Plex Sans
      mono: IBM Plex Mono
      import_from_google: true
    colors:
      accent: "oklch(0.50 0.18 25)"
      bg: "oklch(0.98 0.002 240)"
```

Extra keys under either `ui.frontend` (other than `pack`, `output`, `overwrite`,
`generate`) or `ui.config` are also passed through as `pack_config.<key>` for
custom packs to consume.

## Pack templates

Pack templates read configuration as the top-level `pack_config` variable, for
example `{{ pack_config.app_name }}` or `{{ pack_config.get('colors', {}) }}`.
The API base URL is derived from your `api.basePath` and `api.version` (here
`/api/v1`) and is overridable at runtime via the `VITE_API_BASE_URL`
environment variable.

## What the generated app includes

The `generic` pack scaffolds a complete app shell around your views:

- A sidebar layout with navigation and an always-present Dashboard.
- A login gate and `useAuth()` hook when `require_auth` is true, including SSO
  buttons for any external providers bound to an identity entity.
- Per-entity data hooks and a typed API client under `src/__generated__/`.
- Pages generated from your [views](views), with actions and routes gated by
  each repository's CRUD set (see [Operation-gated UI actions](operation-gating)).

The rest of the `ui:` block is documented separately:

- [UI Generation Overview](overview) -- the layered `ui:` model and generation flow.
- [Collections](collections) -- flattened, formatted presentation models.
- [Components](components) -- the `generic` component catalog and custom components.
- [Views](views) -- pages, routes, the `crud` composite, and `field_roles`.
- [Operation-gated UI actions](operation-gating) -- how CRUD selection drives the UI.
