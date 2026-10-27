# Contributing

## Setup

```console
uv sync --locked
```

This installs the locked dev environment (`pytest`, `pytest-asyncio`,
`pytest-cov`, `ruff`).

## Before opening a PR

```console
uv run --locked ruff check .
uv run --locked pytest
```

`pytest` measures branch coverage for `toolbx` and fails the run
below 90%; add tests alongside any new branch rather than special-casing
the coverage gate. CI runs the same two commands on Python 3.13 and 3.14 —
a change that only works on one of those versions isn't done.

## Conventions

- Follow the code conventions in [AGENTS.md](AGENTS.md): forward-reference
  annotations for Python 3.13, absolute imports, and comments only where they
  explain something the code cannot.
- Keep `toolbx` provider-neutral and free of application-specific
  tools or an agent loop — that scope belongs in consuming projects, not
  here. `experiments/` holds example integrations and isn't part of the
  published package.

## Reporting issues

Open a GitHub issue with a minimal reproduction. For bugs, include the
Python version and the smallest `Toolbox`/`Toolset` setup that reproduces the
problem.
