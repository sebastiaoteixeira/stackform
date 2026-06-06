---
title: "UI Components"
description: Declare reusable named components composed from the generic pack's building blocks.
---

The `ui.components` block lets you declare named components built from the
building blocks shipped by the frontend pack (`generic` is the only built-in
pack today). A declared component can then be referenced by a view or nested
inside another component.

The whole `ui` block is free-form in the JSON schema (`{"type": "object"}`):
every constraint described on this page is checked while the frontend is
generated, not by schema validation. Errors surface as generation failures
(exit 1), not as schema messages.

## Schema

```yaml
ui:
  frontend:
    pack: generic
  components:
    my-card:
      props:
        myEntity: { required: true }
        showOwner: { required: false }
      render:
        component: detail-two-column
        props:
          collection: $myEntity
```

### `props`

Declares the variables the component accepts. Keys are prop names; the value is
an object optionally specifying `required: true` (the default is `false`). A
bare prop name with no object is also accepted and treated as optional.

### `render`

Defines the root of the component as a node:

| Field | Type | Description |
|-------|------|-------------|
| `component` | string | A component name. May be a pack component (such as `list-table`, `detail-two-column`) OR the name of another component you declared under `ui.components`. Required; an unknown name fails generation. |
| `props` | map | Prop values passed to that component. May be references, literals, nested nodes, or component references (see below). |

A node missing `component` fails generation with `Component node missing
'component' field`. An unknown `component` fails with `Component '<name>' not
found in pack` followed by the list of available names.

## Available pack components

The `generic` pack provides kebab-case components, grouped by role. Common ones:

- List views: `list-table` (alias `table`), `list-split-pane`, `list-grouped`,
  `list-card-grid`, `list-spreadsheet`
- Detail views: `detail-two-column`, `detail-tabbed`, `detail-article`,
  `detail-drawer`, `detail-schema`
- Forms: `form-stacked`, `form-sectioned`, `form-modal`, `form-preview`,
  `form-inline-row`
- Auth screens: `auth-centered`, `auth-hero-split`, `auth-tabbed`,
  `auth-signup-role`, `auth-error`
- Composition: `crud`, `split-pane`, `sidebar-layout`
- Reference pickers, empty states, filters, bulk actions, and settings panels
  also exist (for example `ref-dropdown`, `empty-centered`, `filter-toolbar`,
  `delete-simple`, `settings-roles`).

Names such as `Card`, `Button`, `Badge`, and `Input` are internal scaffold
primitives, not components you reference here. Use the kebab-case names above.

## Prop values

A prop value is interpreted by its shape:

- Literal: plain strings, numbers, booleans (for example `mode: "create"`).
- Reference: a string starting with `$`, naming a declared prop of the
  enclosing component (for example `collection: $myEntity`). The reference is the
  bare prop name only. Dotted forms like `$myEntity.title` are not supported: the
  whole string after `$` is treated as the prop name, so `myEntity.title` would
  not match a declared prop and generation fails.
- Nested component: an inline node (an object with a `component` field) defining
  a sub-component.
- Component reference: when the target pack component declares a prop of type
  `component`, a plain string value is taken as the name of another component
  (pack or declared). For example the `crud` component's `list`, `form`,
  `detail`, and `delete` props, or `split-pane`'s `left` and `right` props.

```yaml
render:
  component: split-pane
  props:
    collection: $myEntity       # reference to a declared prop
    ratio: "1:2"                # literal
    left: list-table            # component reference (split-pane.left is type component)
    right:                      # nested component node
      component: detail-two-column
      props:
        collection: $myEntity
```

### Validation of references

Every `$ref` used anywhere in the render tree (including nested nodes) must name
a declared prop of the component. Otherwise generation fails with `render uses
$ref '<name>' but it's not in declared props`. Declared props are not checked
for being unused.

## Rendering behavior today

The render tree is fully parsed and validated, but the generic pack renders only
the root pack component of a view. When a view references a declared component,
the generator follows that component's `render.component` down to its root pack
component and renders that component's template, driven by the view's entity and
collection props.

The abstract render tree (nested nodes, `$ref` wiring, literal props inside
`render`) is validated and recorded but is not yet composed into the generated
output by the `generic` pack. In practice, declaring a component is useful for
naming and for choosing the root pack component (and, via `crud`/`split-pane`,
its sub-components through component references); deeper hand-authored trees are
accepted but inert until a pack consumes them.

## Using a component in a view

A view's `component` may name a pack component directly or one of your declared
components:

```yaml
ui:
  frontend:
    pack: generic
  components:
    my-card:
      props:
        myEntity: { required: true }
      render:
        component: detail-two-column
        props:
          collection: $myEntity
  views:
    my_entity_detail:
      path: /my-collection/:id
      component: my-card
      props:
        collection: myCollection
```

Here `my_entity_detail` resolves `my-card` to its root pack component
`detail-two-column` and renders that, using the view's `collection: myCollection`
prop.
See [Views](./views.md) for how view props drive the chosen component.
