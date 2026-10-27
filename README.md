# toolbx

[![CI](https://github.com/mathisarends/toolbx/actions/workflows/ci.yaml/badge.svg)](https://github.com/mathisarends/toolbx/actions/workflows/ci.yaml)

Provider-neutral Python SDK for LLM tools. Define typed tools once, export their
schemas for your model provider, and execute calls through the same validation
and middleware pipeline.

- Define tools as `@tool` instance methods on a `Toolset`, with shared dependencies
  passed through its constructor.
- Compose toolsets explicitly with `Toolbox(toolsets=(search, admin))`.
- Call Python methods with `call(method, **arguments)` or dispatch model calls
  with `execute(ToolRequest(...))`.
- Export provider-neutral, OpenAI and Anthropic schemas from the same definitions.
- Add dynamic availability, approval, logging and custom middleware.

Your application owns the agent loop and provider adapters. Async tools run on
the event loop; sync tools run in worker threads.

Requires Python 3.13 or newer.

## Installation

```console
uv add toolbx
```

The distribution name and Python import are both `toolbx`.

## Quickstart

```python
import asyncio

from toolbx import Toolbox, Toolset, tool


class CalculatorTools(Toolset, namespace=None):
    @tool("Add two integers")
    def add(self, a: int, b: int = 1) -> int:
        return a + b


async def main() -> None:
    calculator = CalculatorTools()
    toolbox = Toolbox(toolsets=(calculator,))

    result = await toolbox.call(calculator.add, a=2, b=3)
    print(result)  # 5


if __name__ == "__main__":
    asyncio.run(main())
```

Tool methods keep their normal Python calling convention and can be called
and tested directly. Only methods marked with `@tool` become model-facing tools.
Use `toolbox.call(method, **arguments)` to run a registered method through
validation, availability checks and middleware. Calling the method directly
bypasses that pipeline.

For model-generated calls, pass a provider-neutral `ToolRequest` to `execute`:

```python
from toolbx import ToolRequest

toolbox = Toolbox(toolsets=(CalculatorTools(),))
result = await toolbox.execute(
    ToolRequest("add", '{"a": 2, "b": 3}', call_id="call-1")
)
```

`call` resolves the bound method on the exact registered instance, independent
of its exported name or namespace. Unregistered methods raise `LookupError`.
If the same method is registered under multiple names, `call` raises
`ValueError`; select the exported name explicitly with `execute(ToolRequest(...))`.
All keyword arguments to `call`, including `call_id`, belong to the tool.

## Parameters and dependencies

Use typed method parameters or an explicit Pydantic params model:

```python
from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    query: str = Field(description="Text to search for")
    limit: int = Field(default=5, ge=1, le=20)


class CatalogTools(Toolset):
    def __init__(self, client):
        self.client = client

    @tool("Search the catalog", params=SearchParams, tags=["read"])
    async def search(self, params: SearchParams):
        return await self.client.search(params.query, limit=params.limit)

    @tool("Read one product", name="get")
    async def get_product(self, product_id: str):
        return await self.client.get(product_id)


catalog = CatalogTools(client)
toolbox = Toolbox(toolsets=(catalog,))
result = await toolbox.call(catalog.search, query="keyboard")
```

Constructor dependencies never appear in the tool schema. With `params=Model`,
the model fields form the top-level input object and the method receives the
validated model, including nested model instances. Pydantic performs input
validation; signature parameters require type annotations.
An explicit params model requires one receiving method parameter. Its binding
is checked at class definition and cached for execution.
Unknown top-level arguments are rejected in both definition styles. Explicit
params models are adapted without changing the application's model configuration.

A model used in a normal signature stays nested: `create(user: User)` accepts
`{"user": {"name": "Ada"}}`. Adding another method parameter does not change
that shape. Only an explicit `params=User` uses `{"name": "Ada"}` at the top level.
`call` uses the same top-level input fields as `execute`, including for explicit
params models; pass `query="keyboard"`, rather than `params=SearchParams(...)`.

### Schema export

```python
openai_tools = toolbox.to_openai()
anthropic_tools = toolbox.to_anthropic()
native_tools = toolbox.schemas()
```

Exported schemas are independent copies and can be transformed without changing
the registered tool. They leave out the `title` keys Pydantic adds to every model and
field, since they only cost tokens. Nested models still use `$defs`/`$ref`;
`schema.inline_refs()` returns a copy without them for providers that reject
references (recursive models cannot be inlined).

`toolbox.to_openai(strict=True)` emits OpenAI strict-mode schemas: every object
forbids extra keys, every property is required, and optional properties become
nullable. When executing, a `null` for an optional property that does not
itself accept `null` counts as omitted, so the default applies.

## Namespaces and composition

A toolset's default namespace is its class name in snake case, without a
`Tools`, `Toolset` or `Toolbox` suffix. `CatalogTools.search` is exported as
`catalog_search`. Choose a namespace with `class Tools(Toolset, namespace="custom")`
or use `namespace=None` to expose local names directly.

```python
primary = CatalogTools(primary_client)
toolbox = Toolbox(toolsets=(primary,))
toolbox.add(CatalogTools(archive_client), namespace="archive", include={"search"})
```

The constructor accepts a sequence of toolset instances, such as
`toolsets=(primary, archive)` or `toolsets=[primary, archive]`.
An empty `Toolbox()` can be populated later with `add`.

`include` and `exclude` select local tool names. Registration and `merge` are
atomic: a collision leaves the destination unchanged. `merge(other, replace=True)`
explicitly replaces colliding tools. Complete exported names must match
`[A-Za-z0-9_-]{1,64}`.

A toolbox behaves like a read-mostly mapping of exported names to tools:
`toolbox["catalog_search"]` raises `KeyError` for unknown names, `get` returns
`None`, and `in`, `names()` and `remove(name)` work as expected.
`subset(names=..., tags=...)` returns a new toolbox with the matching tools and
the same middleware, for example to give a sub-agent read-only tools:

```python
reader = toolbox.subset(tags={"read"})
```

## Dynamic availability

Availability callbacks receive the toolset instance and are evaluated for each
schema export and execution:

```python
class AdminTools(Toolset):
    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    @tool("Reset the counter", available_when=lambda self: self.enabled)
    def reset(self) -> str:
        return "counter reset"


tools = AdminTools()
toolbox = Toolbox(toolsets=(tools,))
assert toolbox.schemas() == []
tools.enabled = True
assert toolbox.schemas()[0].name == "admin_reset"
```

Unavailable tools are omitted from all schema formats; both `call` and `execute`
raise `LookupError` when invoking them. Construct separate toolset instances for
independent request-specific state.

## Results and errors

`call` and `execute` return the tool's value unchanged. Validation errors and tool
exceptions propagate to the caller. There is no result wrapper; the agent loop
maps exceptions into its provider's error format and serializes values.
`to_text(result)` covers the common case: strings pass through unchanged, and
everything else, including Pydantic models, becomes JSON.
`OutputBudget(max_chars=20_000).truncate(text)` caps long text, including
truncation markers, while retaining both ends where the budget permits.

`ErrorBoundaryMiddleware` is optional. When explicitly installed, it logs
exceptions and turns them into `"Tool failed: ..."` strings. Applications that
need to distinguish errors should handle exceptions directly or supply their
own middleware. Cancellation propagates.

## Parallel calls

```python
from toolbx import ToolRequest

results = await toolbox.execute_many([
    ToolRequest("catalog_search", '{"query": "first"}', call_id="call-1"),
    ToolRequest("catalog_search", {"query": "second"}, call_id="call-2"),
])
```

Calls run concurrently and results retain input order. By default, failed calls
contribute their exception to the result list; use `return_exceptions=False` to
propagate the first failure. Invalid JSON is also an exception.

Async methods run on the event loop; sync methods run in worker threads.
Cancelling a batch cancels its outstanding calls. Cancellation stops awaiting
a sync call but cannot stop its already running thread.

## Middleware and metadata

```python
from toolbx import CallLoggingMiddleware, ToolCall, ToolHandler


async def trace(call: ToolCall, call_next: ToolHandler) -> object:
    print(call.call_id, call.name)
    return await call_next(call)


toolbox = Toolbox(
    toolsets=(CalculatorTools(),),
    middleware=[trace, CallLoggingMiddleware()],
)
```

Call logging emits tool names and durations at INFO; raw arguments require DEBUG.

Middleware runs in declaration order around validation and execution. `ToolCall`
contains the name, parsed `arguments`, optional `call_id` and registered tool.
JSON decoding happens before middleware dispatch. Use
`dataclasses.replace(call, arguments=...)` when forwarding changed arguments.

### Metadata

Without a description argument, `@tool()` uses the method's docstring; a tool
with neither is rejected at class definition.

`@tool` supports the keyword-only `name`, `tags`, `metadata` and
`requires_approval`. These runtime hints are available on each registered
`Tool`, e.g. `toolbox["catalog_search"].tags`.

### Approval

`requires_approval` is either a bool or a predicate over the validated params.
`ApprovalMiddleware` enforces it: it calls a sync or async `confirm(call)` and
returns a decline message instead of running the tool when the answer is no.

```python
from toolbx import ApprovalMiddleware


class BankTools(Toolset):
    @tool("Transfer money", params=Transfer, requires_approval=lambda p: p.amount > 100)
    def transfer(self, params: Transfer) -> str: ...


async def confirm(call: ToolCall) -> bool:
    return await ask_user(f"Run {call.name}({call.arguments})?")


toolbox = Toolbox(
    toolsets=(BankTools(),),
    middleware=[ApprovalMiddleware(confirm)],
)
```

Without the middleware, `requires_approval` does not gate execution;
`tool.approval_required(arguments)` evaluates it for custom agent loops. Invalid
arguments fail validation before the user is asked.

## Migration

### 0.4.0

This API deliberately breaks earlier versions:

- Install `toolbx` instead of `mm-agenttoolkit` and import from `toolbx`
  instead of `toolbox` or `agenttoolkit`.
- Define tools on `Toolset` subclasses; replace `@toolbox.tool`, `register` and
  `add_plugin` with `@tool` methods and `Toolbox(...)/add(...)`.
- Pass dependencies through toolset constructors. `Inject`, `ToolContext`,
  dependency providers and the context-based binding helpers are removed.
- Use `Toolbox` directly; `ToolRegistry` is removed.
- Replace `get_schema` and `ToolSchemaFormat` with `schemas`, `to_openai` or
  `to_anthropic`.
- `Tool.namespace` replaces `Tool.plugin_name`. Raw invocation helpers on
  `Tool` are internal; use `Toolbox.execute` for dispatched calls.

### Unreleased

Changes since 0.4.0 that break existing code:

- Pass toolset instances as a sequence: `Toolbox(toolsets=(tools,))` replaces
  `Toolbox(tools)`, and `Toolbox(toolsets=(first, second))` replaces
  `Toolbox(first, second)`.
- `execute(ToolRequest(name, arguments, call_id=...))` replaces
  `execute(name, arguments, call_id=...)`. Use `call(tools.method, **arguments)`
  for Python calls through the same pipeline. `execute_many` still accepts a
  sequence of `ToolRequest` objects.
- Names are unified: `Tool(params_model=)`, `build_schema(params_model=)` and
  `tool.params_model` replace `param_model`; `tool.input_schema` and
  `ToolSchema.input_schema` replace `parameters`; `ToolCall.arguments` replaces
  `raw_args`; `tool.metadata` replaces `tool.extra` and `ToolMetadata` is
  removed; `OutputBudget.truncate()` replaces `shape()`.
- Exported schemas no longer contain Pydantic `title` keys.
- `Tool` objects compare by identity, no longer by name.
- `ApprovalMiddleware` replaces hand-written approval checks before `execute`.
- `@tool` accepts `name` only as a keyword and rejects tools without a
  description or docstring.

## Examples and development

- [Class-based toolsets](examples/class_based_toolsets.py)
- [Constructor dependencies](examples/constructor_dependencies.py)
- [Dynamic availability](examples/availability_gating.py)
- [Schema export](examples/schema_export.py)
- [Custom middleware](examples/custom_middleware.py)
- [Approval](examples/approval.py)

```console
uv sync --locked
uv run --locked ruff check .
uv run --locked pytest
```

Tests enforce 90% branch coverage. CI runs on Python 3.13 and 3.14.
`experiments/` contains an example chat integration and is excluded from the
published package. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT; see [LICENSE.md](LICENSE.md).
