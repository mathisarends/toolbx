# toolbox

Provider-neutral tool definitions and execution for Python agents. Define tools
as instance methods on a `Toolset`, pass dependencies through its constructor,
and compose the instances in a `Toolbox`. The package supplies schemas,
validation and middleware; your application owns the agent loop and adapters.

Requires Python 3.13 or newer.

## Installation

```console
uv add mm-agenttoolkit
```

The distribution name is `mm-agenttoolkit`; the Python import is `toolbox`.

## Quickstart

```python
from toolbox import Toolbox, Toolset, tool


class CalculatorTools(Toolset, namespace=None):
    @tool("Add two integers")
    def add(self, a: int, b: int = 1) -> int:
        return a + b


toolbox = Toolbox(CalculatorTools())
openai_tools = toolbox.to_openai()
anthropic_tools = toolbox.to_anthropic()
native_tools = toolbox.schemas()

result = await toolbox.execute("add", '{"a": 2, "b": 3}', call_id="call-1")
assert result == 5
```

Tool methods keep their normal Python calling convention and can be called
and tested directly. Only methods marked with `@tool` become model-facing tools.

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


toolbox = Toolbox(CatalogTools(client))
result = await toolbox.execute("catalog_search", {"query": "keyboard"})
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

## Namespaces and composition

A toolset's default namespace is its class name in snake case, without a
`Tools`, `Toolset` or `Toolbox` suffix. `CatalogTools.search` is exported as
`catalog_search`. Choose a namespace with `class Tools(Toolset, namespace="custom")`
or use `namespace=None` to expose local names directly.

```python
toolbox = Toolbox(CatalogTools(primary_client))
toolbox.add(CatalogTools(archive_client), namespace="archive", include={"search"})
```

`include` and `exclude` select local tool names. Registration and `merge` are
atomic: a collision leaves the destination unchanged. `merge(other, replace=True)`
explicitly replaces colliding tools. Complete exported names must match
`[A-Za-z0-9_-]{1,64}`.

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
toolbox = Toolbox(tools)
assert toolbox.schemas() == []
tools.enabled = True
assert toolbox.schemas()[0].name == "admin_reset"
```

Unavailable tools are omitted from all schema formats and direct execution
raises `LookupError`. Construct separate toolset instances for independent
request-specific state.

## Results and errors

`execute` returns the tool's value unchanged. Validation errors and tool
exceptions propagate to the caller. There is no result wrapper; the agent loop
maps exceptions into its provider's error format and serializes values.

`ErrorBoundaryMiddleware` is optional. When explicitly installed, it logs
exceptions and turns them into `"Tool failed: ..."` strings. Applications that
need to distinguish errors should handle exceptions directly or supply their
own middleware. Cancellation propagates.

## Parallel calls

```python
from toolbox import ToolRequest

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
from toolbox import CallLoggingMiddleware, ToolCall, ToolHandler


async def trace(call: ToolCall, call_next: ToolHandler) -> object:
    print(call.call_id, call.name)
    return await call_next(call)


toolbox = Toolbox(CalculatorTools(), middleware=[trace, CallLoggingMiddleware()])
```

Call logging emits tool names and durations at INFO; raw arguments require DEBUG.

Middleware runs in declaration order around validation and execution. `ToolCall`
contains the name, parsed `raw_args`, optional `call_id` and registered tool.
JSON decoding happens before middleware dispatch. Use
`dataclasses.replace(call, raw_args=...)` when forwarding changed arguments.

`@tool` supports `name`, `tags`, `metadata` and `requires_approval`. These runtime
hints are available through `toolbox.get(name)` and iteration. Approval remains
an agent-loop responsibility; `requires_approval` does not gate execution.

Exported schemas are independent copies and can be transformed without changing
the registered tool. `OutputBudget` is available for tools that return long text.

## Migration

This API deliberately breaks earlier versions:

- Import from `toolbox` instead of `agenttoolkit`.
- Define tools on `Toolset` subclasses; replace `@toolbox.tool`, `register` and
  `add_plugin` with `@tool` methods and `Toolbox(...)/add(...)`.
- Pass dependencies through toolset constructors. `Inject`, `ToolContext`,
  dependency providers and the context-based binding helpers are removed.
- Use `Toolbox` directly; `ToolRegistry` is removed.
- Replace `get_schema` and `ToolSchemaFormat` with `schemas`, `to_openai` or
  `to_anthropic`.
- `Tool.namespace` replaces `Tool.plugin_name`. Raw invocation helpers on
  `Tool` are internal; use `Toolbox.execute` for dispatched calls.

## Examples and development

See `examples/class_based_toolsets.py`, `examples/constructor_dependencies.py`,
`examples/availability_gating.py`, `examples/schema_export.py`,
`examples/custom_middleware.py` and `examples/approval.py`.

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
