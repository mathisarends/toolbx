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

`pytest` measures branch coverage for `toolbox` and fails the run
below 90%; add tests alongside any new branch rather than special-casing
the coverage gate. CI runs the same two commands on Python 3.13 and 3.14 —
a change that only works on one of those versions isn't done.

## Conventions

- Python 3.13 evaluates annotations eagerly, so any module using a
  forward reference (a class referencing its own name, or a name defined
  later in the file) needs `from __future__ import annotations` at the
  top. This isn't needed on 3.14 (PEP 649), but the project supports both,
  so add it whenever it would matter on 3.13.
- Use absolute imports (`from toolbox.tools.context import
  ToolContext`), not relative imports — except in `__init__.py` files,
  which use relative imports to re-export their package's public API.
- Don't add comments or docstrings that just restate what the code already
  says. Only write one when it explains something a reader couldn't get
  from the code itself: why something exists, a hidden constraint, or a
  behavior that would otherwise be surprising.
- Keep `toolbox` provider-neutral and free of application-specific
  tools or an agent loop — that scope belongs in consuming projects, not
  here. `experiments/` holds example integrations and isn't part of the
  published package.

## Reporting issues

Open a GitHub issue with a minimal reproduction. For bugs, include the
Python version and the smallest `Toolbox`/`Tool` setup that reproduces the
problem.
