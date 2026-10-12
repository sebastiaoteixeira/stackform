---
title: "UI Generation Overview"
description: Define a React frontend in the YAML spec and generate it with the build CLI.
---

The `ui:` block describes a frontend alongside the backend. When it is present, the
generator scaffolds a Vite + React + TypeScript + Tailwind project from the
configured pack. The only built-in pack is `generic`, a wireframe-style CRUD UI.

## Concepts

The `ui:` definition is layered:

- **Frontend settings (`ui.frontend`):** which pack to use and how to handle
  existing files (`pack`, `overwrite`).
- **App config (`ui.config`):** app name, theme (fonts and colors), and the login
  gate (`require_auth`).
- **Collections (`ui.collections`):** flattened, presentation-oriented views over
  API entities, validated at generate time.
- **Components (`ui.components`):** reusable building blocks composed from the
  pack's component catalog.
- **Views (`ui.views`):** page-level routes that wire a pack component (or a custom
  component) to a collection or entity.

## Basic structure

```yaml
api:
  basePath: /api
  version: v1

ui:
  frontend:
    pack: generic
    overwrite: never

  config:
    app_name: MyApp
    require_auth: true

  views:
    myCollection:
      path: /my-collection
      component: crud
      props:
        collection: myCollectionList
        field_roles:
          title: title
          content: body
```

## App config

`ui.config` (merged with any extra keys under `ui.frontend`) themes the app and
controls the login gate:

- `app_name` -- shown in the sidebar brand and topbar.
- `require_auth` -- when `true` (the default), the whole app is gated behind a login
  page until a token is present; when `false`, pages render without a login.
- `fonts` -- `ui`, `hand`, `mono`, `import_from_google`, `use_handwritten_titles`.
- `colors` and `colors_dark` -- CSS variables for the light and dark themes
  (background, surface, ink, accent, danger, etc.); any key you omit falls back to a
  built-in default.

## Views

Each key under `ui.views` becomes a page. The view name is PascalCased into a page
file, and its `path` becomes both a React Router route and a sidebar nav item. A
`Dashboard` route at `/` is always generated.

- `component` -- a pack component (for example `list-table`, `detail-two-column`,
  `auth-hero-split`) or one of your own `ui.components`.
- `props.collection` -- the collection or entity the view reads.
- `props.field_roles` -- maps semantic slots (`title`, `content`, `status`, `date`)
  to entity field names so the pack components know what to render.

The `crud` composite component is the common case for a managed resource. A single
`crud` view emits three page files (list, form, detail) and up to four routes:

```yaml
views:
  myCollection:
    path: /my-collection
    component: crud
    props:
      collection: myCollection
      list: list-table
      form: form-stacked
      detail: detail-two-column
```

This generates `/my-collection` (list), `/my-collection/new` (create),
`/my-collection/:id` (detail), and `/my-collection/:id/edit` (edit).

## Operation-gated actions

The generated app only renders actions and routes for CRUD operations the backing
repository actually exposes. If a repository's `crud:` set omits `update`, the
detail page shows no Edit button and the `/:id/edit` route is not emitted; omitting
`create` removes the New action and the `/new` route. This keeps the UI in step with
the backend surface. See the [operation-gating reference](operation-gating.md) and
[Composable per-operation CRUD](../repositories/composable-crud.md).

## Authentication

When the spec has a `type: auth` entity, the app adds a login gate and the auth
lifecycle:

- A `/login` page (the built-in form, or a view you bind to `path: /login`).
- `useAuth()` with `login`/`logout` and a stored JWT.
- External SSO buttons, fetched live from
  `GET {basePath}[/{version}]/{collection}/auth/providers`, plus an
  `/auth/callback` route that consumes the redirect token from SSO.

Login posts to `.../{collection}/login` and stores the `{token, user}` response.

## Collections and components

`ui.collections` are flattened views over entities, validated and type-resolved at
generate time (unknown entities or fields fail the build). The pack's component
catalog (list, detail, form, auth, empty-state, delete, filter, and ref-picker
variants) is referenced by the kebab-case names shown in the pack. See
[collections](collections.md) and [components](components.md) for details.

## Generation

There is no `frontend` or `compile` command. Generate the UI with `stackform build`:

```bash
# Frontend only (uses ui.frontend.output, then ./frontend)
stackform build myapp.yaml frontend

# Everything: backend, frontend, and deploy artifacts
stackform build myapp.yaml all -o ./target
```

Output paths:

- `stackform build myapp.yaml frontend -o ./web` writes the frontend to `./web`.
- Without `-o`, a frontend-only build uses `ui.frontend.output`, then
  `./frontend` when the spec does not declare an output.
- `stackform build myapp.yaml all -o ./target` writes the frontend to
  `target/frontend` (and the backend to `target/backend`).

If the spec has no `ui:` block, a frontend-only build prints
`Error: No 'ui' block found in the YAML spec.`; a missing `ui.frontend.pack` prints
`Error: ui.frontend.pack is required.` Both exit with status 1.

## Editable vs generated files

Generated files land in two zones. Scaffolding, hooks, and types go under
`src/__generated__/` and are overwritten on every build. Page files (under
`src/pages/`) are editable and preserved according to `ui.frontend.overwrite`
(`never` keeps your edits; `always` regenerates). The API base URL comes from the
spec's `basePath`/`version` (overridable at runtime with `VITE_API_BASE_URL`), and
the dev server proxies `/api` to `http://localhost:8000`.
