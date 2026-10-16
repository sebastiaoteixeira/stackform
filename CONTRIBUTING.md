# Contributing to Stackform

Thanks for your interest in the project. This guide covers the development setup, the test suite,
and what a reviewable change looks like.

## Development setup

The project is managed with [uv](https://docs.astral.sh/uv/). A locked environment for the
supported interpreters is created with:

```bash
uv sync --locked --all-extras
```

A plain virtual environment works too:

```bash
pip install -e ".[dev]"
```

Python 3.11 or newer is required. The integration suite additionally needs a MongoDB instance:

```bash
docker run -d --name stackform-mongodb -p 27017:27017 mongo:8
```

## Running the tests

```bash
uv run pytest -m "not integration"   # unit suite, no services required
uv run pytest -m integration         # integration suite, needs MongoDB
uv run pytest                        # everything
```

GitHub Actions runs the unit suite on Python 3.11 and 3.13 for every push to `main` and every pull
request. A pull request whose unit suite is red is not reviewed.

## Where the code lives

| Path | Responsibility |
| --- | --- |
| `src/yaml_api_generator/parsers/` | JSON Schema validation, desugaring, and version transformers that read a spec into the IR |
| `src/yaml_api_generator/ir/` | the intermediate representation every generator consumes |
| `src/yaml_api_generator/generators/` | backend, frontend and deploy emitters |
| `src/yaml_api_generator/server/` | the development server that runs a spec without compiling it |
| `src/yaml_api_generator/cli/` | the `stackform` command |
| `examples/` | the specification corpus; `valid/` and `invalid/` are consumed by the tests |
| `docs/` | the manual, published to the documentation site on merge |

## Changing the specification language

The language is versioned, and each version has its own schema under
`src/yaml_api_generator/parsers/schemas/`. A change to the language is only complete when all of
the following land together:

1. the schema for the version that introduces it,
2. a transformer under `parsers/transformers/` if an older version must keep parsing,
3. an example under `examples/valid/` (and, where the change adds a rejection, one under
   `examples/invalid/`),
4. unit tests covering both the accepted and the rejected shapes,
5. the manual page under `docs/` for that version.

A specification feature with no example is treated as undocumented and will be asked for in review.

## Pull requests

- Branch from `main`, named `<type>/<subject>` — for example `fix/login-route-404` or
  `feat/field-level-scoping`.
- One concern per pull request. A refactor bundled with a behaviour change is split before review.
- The title states the change in the imperative, and the body says what a reviewer should check.
- Keep generated output, local scratch files and client material out of the commit; `git status`
  should be clean of them before you stage.

## Reporting issues

Open an issue with the specification that reproduces the problem, the command you ran, and the
observed against the expected output. A minimal spec that still fails is worth more than a large
one that fails for several reasons at once.

## Licence

Stackform is released under the MIT licence. By contributing you agree that your contribution is
licensed under the same terms.
