# Service `input:` and `with:` forwarding

A v0.3 service is an orchestration layer: it declares the inputs it needs, has
them validated before it runs, and forwards them to whatever backs it -- a
repository operation or a handler. Both constructs are v0.3-only; a v0.2 spec
never carries them and behaves byte-identically.

## `input:` -- declaring and validating inputs

`input:` names the fields a service requires. It is either an inline field map
or a list of named DTOs whose fields are merged:

```yaml
services:
  archivePost:
    repository: posts
    operation: archive
    input:
      postId: string        # inline: field name -> type
  publishPost:
    handler: app.handlers.publish
    input: [PublishRequest]  # merge the fields of a named DTO
```

Inputs are drawn from the request -- path parameters and the JSON body -- and
type-checked against their declarations using the same rules as request-body
validation. A missing or ill-typed input aborts the request with **422** and the
service never runs; nothing downstream (repository or handler) executes.

Declared inputs are required by default. Mark one optional with an explicit
field config:

```yaml
    input:
      cursor:
        type: string
        required: false
```

## `with:` -- forwarding inputs

`with:` maps a downstream name to a value taken from the validated inputs. Each
right-hand side is a `$symbol` naming an input field, or a literal (a quoted
string, a number, or `true`/`false`):

```yaml
services:
  archivePost:
    repository: posts
    operation: archive
    input:
      postId: string
    with:
      id: $postId          # populate the repository operation's $id free-symbol
      state: 'archived'    # a literal forwarded verbatim
```

For a service backed by a **repository operation**, the forwarded values
populate the operation's free-symbols (the `$`-symbols in its `query:` filter).
For a service backed by a **handler**, the resolved values are available on the
request context as `ctx.service_inputs`.

## Symbol scope

A `with:` right-hand-side `$symbol` resolves against the **input field names**
only -- there is no ambient `$principal` or request root at this site. A
reference to a name the service did not declare as an input aborts generation
with the uniform `UNDEFINED_SYMBOL` error, naming the symbol and the scope
(`service '<name>' with '<key>'`). A `with:` made entirely of literals needs no
`input:`.

## Error codes

| Code | Raised when |
| --- | --- |
| `SERVICE_INPUT_INVALID` | `input:` is neither a field map nor a list of DTO names |
| `SERVICE_INPUT_DTO_NOT_FOUND` | `input:` lists a DTO that is not defined |
| `UNDEFINED_SYMBOL` | a `with:` `$symbol` is not a declared input field |
