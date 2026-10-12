---
title: "UI Views"
description: Page-level routes that the generated React app renders, plus the crud composite, field_roles, and auth views.
---

The `ui.views` block defines your application's routing map. Each entry becomes a
page in the generated React app: a route in the app shell, a sidebar nav item, and
one or more page files under `src/pages/`.

The whole `ui` block is free-form in the JSON schema; everything below is validated
at generate time (`stackform build <file> frontend` or `... all`), not against the
schema. The only built-in pack is `generic`, so all component names refer to that
pack.

## Schema

```yaml
api:
  basePath: /api
  version: v1
ui:
  frontend:
    pack: generic
  config:
    app_name: My App
  views:
    my-collection:
      path: /my-collection
      component: crud
      props:
        collection: myCollection
        field_roles:
          title: title
          content: body
```

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | The client-side React Router path (e.g. `/my-collection`, or `:id` segments like `/my-collection/:id`). |
| `component` | string | The root component for the view. May name a `generic` pack component (e.g. `crud`, `table`, `list-table`) or a custom one declared in `ui.components`. Required. |
| `props` | map | Values passed to the root component. See "Prop value forms" below. |

## How a view is generated

Each view key is PascalCased to produce its page file and React component name. A
view named `my_collection_list` generates `src/pages/MyCollectionList.tsx`, imports it in the app
shell, and registers a route at the view's `path`.

- Sidebar nav: every view gets a sidebar entry whose label is derived from `path`
  (slashes stripped, underscores spaced, title-cased). Views at `path: /` and
  `path: /login` are excluded from the nav list.
- Dashboard: the app shell always renders a built-in Dashboard at `/`, with a
  Dashboard nav item, regardless of your views. Give a view `path: /` to replace
  the page content at that route.
- The page files land in the editable zone (`src/pages/`), so you can hand-edit
  them; regeneration with `overwrite: never` leaves them untouched.

## The `crud` composite

`component: crud` is the high-level way to wire a full resource UI. One view
generates three page files and four routes:

```yaml
ui:
  views:
    my-collection:
      path: /my-collection
      component: crud
      props:
        collection: myCollection
        list: list-table
        form: form-stacked
        detail: detail-two-column
        delete: delete-simple
```

Generated for the view above:

- Page files: `MyCollection.tsx` (list), `MyCollectionForm.tsx` (create/edit),
  `MyCollectionDetail.tsx` (single record).
- Routes: `/my-collection` (list), `/my-collection/new` (create form),
  `/my-collection/:id` (detail), `/my-collection/:id/edit` (edit form).

The `list`, `form`, `detail`, and `delete` props are component references that pick
which pack variant fills each slot. They default to `list-table`, `form-stacked`,
`detail-two-column`, and `delete-simple` when omitted, so the minimal form is just
`component: crud` with a `collection`.

The `:id`, `/new`, and `/:id/edit` routes are operation-gated: each one is emitted
only if the collection's backing repository exposes the corresponding CRUD
operation. With `crud: [list, get]` on the repository, the create form (`/new`),
edit form (`/:id/edit`), and their New/Edit buttons are all omitted, and the page
becomes read-only. See [Operation-gated UI actions](operation-gating.md) and
[Composable per-operation CRUD](../repositories/composable-crud.md).

## `field_roles`

`field_roles` maps semantic display roles to entity field names. The list, detail,
and form templates read it to decide which fields to feature (for example, which
field is the title and which is the body or status). It does not rename or hide
fields at the API level; it only influences how the generic pack lays them out.

```yaml
props:
  collection: myCollection
  field_roles:
    title: title
    content: description
    status: status
    date: createdAt
```

Recognized role keys in the generic pack include `title`, `content`, `status`, and
`date`. Unmapped fields still render; the mapped ones are surfaced first.

## Auth views

Authentication pages are wired automatically when your spec has an identity
(`type: auth`) entity, but you can also declare a custom login view by giving it
`path: /login`. The app shell then renders your view at `/login` instead of its
built-in login page. Use one of the `auth-*` pack components:

```yaml
ui:
  views:
    login:
      path: /login
      component: auth-hero-split
      props:
        hero_content:
          title: Welcome back.
          signup_title: Get started.
          subtitle: Welcome to my-app.
          quote: The platform that changed how we work.
```

Auth components such as `auth-hero-split` and `auth-tabbed` accept `providers`
(populated from your configured external providers), `allow_register`, and the
`hero_content` object shown above. External SSO buttons are rendered from the
`GET {basePath}[/{version}]/{collection}/auth/providers` endpoint, and a successful
SSO login lands on `/auth/callback?code=...`, which the app shell redeems for a token
at `/auth/exchange`. See
[Login, SSO, and the token flow](../auth/login-and-sso.md).

> **Enforcement status**
>
> Roles (exact match), `<entity>:*` scoping, and ownership/ABAC `when` rules
> are enforced by the generated FastAPI backend, the generated DRF backend, and the
> `stackform run` dev server alike. A request that fails a rule gets 401 (missing or
> invalid credentials), 403 (authenticated but not allowed), or 404 (record not
> found, checked before ownership). Two current limitations: role hierarchy (for
> example `admin` inheriting `moderator`) is accepted in YAML but not yet applied
> during enforcement -- only exact role matches are checked; and conditional or
> ownership rules require a v0.2 spec, because v0.1 specs do not parse `when` rules.

The UI gates which controls it shows, but it is not a security boundary: the
generated backend enforces access on every request regardless of what the UI
renders.

## Prop value forms

`props` values can take several shapes, all resolved at generate time:

- Literal scalar: `mode: create`, `searchable: true`.
- Object/map: nested maps like `hero_content` or `field_roles`.
- Component reference (`crud`-style slots): a bare pack component name for a prop
  declared with `type: component` (e.g. `list: list-table`).
- `$ref` string: `$myEntity` binds the value to a prop named `myEntity` declared on a
  custom `ui.components` entry. Dotted forms like `$myEntity.title` are not supported.
- Nested component: an inline `{ component: ..., props: ... }` map.

A `collection` prop names a `ui.collections` entry or a backing entity. You can also
reference a collection from a route param using the `name[param]` form (for example
`my-collection[id]`); see [UI Collections](collections.md).

## Resolving view components

A view's `component` may name a `generic` pack component directly, or a custom
component declared in `ui.components`. A custom component resolves through its
render tree down to the root pack component, which determines the page layout. The
generic pack renders only that root pack component; nested render-tree props are
validated but inert today. See [UI Components](components.md).
