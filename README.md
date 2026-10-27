# toolbox

`toolbox` provides one provider-neutral definition for tools exposed to
LLM agents. Define a tool once — schema, availability, metadata, and
execution logic — and expose it to OpenAI, Anthropic, or any other provider
without duplicating definitions.

It intentionally contains no application-specific tools and no agent loop:
it is a building block, not a framework.

## Table of contents

- [Installation](#installation)
- [Quickstart](#quickstart)
- [Defining tools](#defining-tools)
- [Grouping tools in toolsets](#grouping-tools-in-toolsets)
- [Tool metadata](#tool-metadata)
- [Driving an agent loop](#driving-an-agent-loop)
- [Results and errors](#results-and-errors)
- [Dependency injection](#dependency-injection)
- [Conditional availability and descriptions](#conditional-availability-and-descriptions)
- [Middleware](#middleware)
- [Merging registries](#merging-registries)
- [Putting it together](#putting-it-together)
- [Features](#features)
- [Development](#development)
- [License](#license)

## Installation

```console
uv add mm-agenttoolkit
```

Requires Python 3.13+. On 3.13, modules that use forward references need
`from __future__ import annotations`, since lazy annotation evaluation
(PEP 649) is only native starting with 3.14.

## Quickstart

Define a tool, give its schema to the model, and execute the call the model
makes:

```python
from toolbox import Toolbox

toolbox = Toolbox()


@toolbox.tool("Add two integers.")
def add(a: int, b: int) -> int:
    return a + b


# 1. Send the schema to the model.
schema = toolbox.to_anthropic()

# 2. The model asks to call "add" with {"a": 2, "b": 3}.
result = await toolbox.execute("add", {"a": 2, "b": 3})  # 5

# 3. Serialize the value and feed it back to the model.
```

That is the whole core loop. Everything below is optional and independent:
add only the pieces an application actually needs.

## Defining tools

The `@toolbox.tool(...)` decorator is the entire surface most code touches.
Parameters and their JSON Schema come from the function signature:

```python
@toolbox.tool("Add two integers.")
def add(a: int, b: int) -> int:
    return a + b
```

For richer validation or field descriptions, take a single Pydantic model
parameter instead. It is detected automatically and used directly for
validation and schema generation:

```python
from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    query: str = Field(description="What to search for")
    limit: int = Field(default=5, ge=1, le=20)


@toolbox.tool("Search the connected knowledge base.")
async def search(params: SearchParams) -> list[str]:
    return await run_search(params.query, params.limit)
```

Tools may be synchronous or asynchronous; both run behind the same async API.

Use `toolbox.register(tool)` when you already have a `Tool` object and want to
register it imperatively. Pass `replace=True` to replace a tool with the same
name.

## Grouping tools in toolsets

For larger applications, group related tools in a `Toolset` subclass and
inject stable application services through its constructor. The `@tool`
decorator marks methods without registering them; `Toolbox` registers all marked
methods of an instance together:

```python
from toolbox import Toolset, Toolbox, tool


class CatalogTools(Toolset):
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    @tool("Search the product catalog")
    async def search(self, query: str, limit: int = 10) -> list[Product]:
        return await self._catalog.search(query, limit=limit)

    @tool("Get one product", name="get")
    async def get_product(self, product_id: str) -> Product:
        return await self._catalog.get(product_id)

    def normalize(self, query: str) -> str:
        # Undecorated methods are never exposed to the model.
        return " ".join(query.split())


toolbox = Toolbox(CatalogTools(catalog_service))
toolbox.add(AdminTools(admin_service), exclude={"delete_user"})
```

The namespace prefixes every exposed method: the example registers
`catalog_search` and `catalog_get`. It defaults to the snake_case class name
without a `Tools`, `Toolbox`, `Toolset` or `Plugin` suffix. Set it with a
class keyword (`class CatalogTools(Toolset, namespace="shop")`), or use
`namespace=None` to expose the local names unprefixed. Pass `namespace=` to
`toolbox.add(...)` to register a second instance of the same class.
`include=` and `exclude=` select tools by their local name; unknown names are
rejected.

Mistakes surface as early as possible. Invalid or duplicate tool names and
`classmethod`/`staticmethod` tools raise when the class is defined. Name
collisions are reported when a toolset is added, listing every conflicting tool
and the toolset which already owns it. Registration is atomic: a failure leaves
the registry unchanged.

Toolsets are fully constructed by the application and are not connected to the
dependency container. Their methods contain only model-facing parameters;
`Inject[T]` is intentionally rejected there. The application's composition root
owns the toolset, its dependencies, and their lifecycle. Objects which do not
inherit from `Toolset` can still be registered with
`toolbox.add(obj, namespace="name")` or `toolbox.add_plugin(obj, name="name")`.
See the runnable [`class_based_plugins.py`](examples/class_based_plugins.py)
example for the complete setup.

## Tool metadata

A tool can carry information for the host loop that dispatches the call.
None of it is visible to the model — it never appears in the generated JSON
Schema:

```python
@toolbox.tool(
    "Issue a refund for an order.",
    tags=["billing", "write"],
    requires_approval=True,
    metadata={"owner": "billing-team"},
)
def refund(params: RefundParams) -> str: ...
```

- `tags` — a `frozenset[str]` for grouping or filtering tools, readable as
  `tool.tags`.
- `metadata` — an arbitrary read-only mapping for anything else the host
  application needs, readable as `tool.extra`.
- `requires_approval` — readable as `tool.requires_approval`; check it
  before calling `toolbox.execute(...)` if the call needs user confirmation
  first. `toolbox` does not enforce approval itself.

```python
tool = toolbox.get("refund")
tool.tags                # frozenset({"billing", "write"})
tool.extra["owner"]      # "billing-team"
tool.requires_approval   # True
```

## Driving an agent loop

`Toolbox.schemas(...)` returns the schema for every tool available in the
active (or a given) context; `Toolbox.execute(...)` dispatches a model-produced
call:

```python
openai_schemas = toolbox.to_openai()
anthropic_schemas = toolbox.to_anthropic()

result = await toolbox.execute("search", {"query": "tool middleware"}, context=context)
```

Code that only registers or executes tools, independent of how they are shown
to a model, can accept the shared `Toolbox` type.

A typical loop confirms approval-gated tools before executing:

```python
tool = toolbox.get(name)
if tool is not None and tool.requires_approval and not confirm(name, arguments):
    result = "Tool failed: Declined by user"
else:
    result = await toolbox.execute(name, arguments, context=context)
```

Iterating a `Toolbox` instance yields the underlying `Tool` objects — every
registered one, gated or not. Filter with `tool.is_available(context)` to print
a catalog of what a given context actually exposes (`tool.name`,
`tool.resolve_description(context)`, `tool.tags`, ...).

## Results and errors

Tool functions return their natural Python value: text, numbers, collections,
Pydantic models, or `None`. `Toolbox.execute()` passes that value through
unchanged:

```python
class WeatherResult(BaseModel):
    city: str
    temp_c: float


@toolbox.tool("Get the current weather for a known city")
def get_weather(city: str) -> WeatherResult:
    temp_c = KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        raise ValueError(f"Unknown city: {city!r}")
    return WeatherResult(city=city, temp_c=temp_c)
```

With `ErrorBoundaryMiddleware` enabled, exceptions from resolution, validation,
middleware, dependency injection, or the tool itself are logged and converted
to an agent-readable string prefixed with `"Tool failed: "`. Consequently tool
implementations need no toolkit-specific result import. Without that
middleware, exceptions propagate to the caller normally.

Because dispatch by name is dynamic and one registry can contain heterogeneous
return types, the static return type of `Toolbox.execute()` is `object`. The
application's provider adapter owns serialization and can add any
provider-specific metadata at that boundary.

## Dependency injection

A tool that needs a client, a session, or a connection declares it as an
`Inject[T]` parameter. Such parameters are resolved at execution time and
never appear in the model-facing schema:

```python
from toolbox import DependencyProvider, Inject, Toolbox, provide


class Dependencies(DependencyProvider):
    @provide
    def client(self) -> SearchClient:
        return SearchClient()


toolbox = Toolbox(dependencies=[Dependencies()])


@toolbox.tool("Search the connected knowledge base.")
async def search(query: str, client: Inject[SearchClient]) -> list[str]:
    return await client.search(query)
```

Dependencies are declared on `DependencyProvider` classes. The container
validates missing definitions, duplicates, and cycles when it is constructed.
Every dependency is a singleton: it is created on first use and the same
instance is reused by every subsequent tool call.

Singleton dependencies need no context manager:

```python
await toolbox.execute("search", {"query": "dependency injection"})
```

Factory methods may be synchronous or asynchronous. Generator providers are
intentionally unsupported: the application owns external resource lifecycles
and passes ready instances into its provider:

```python
class Dependencies(DependencyProvider):
    def __init__(self, database: Database) -> None:
        self._database = database

    @provide
    def database(self) -> Database:
        return self._database


async with Database.connect() as database:
    toolbox = Toolbox(dependencies=[Dependencies(database)])
    await toolbox.execute("search", {"query": "dependency injection"})
```

`Toolbox` never closes injected resources. The composition root that created a
resource also decides when to close it.

## Conditional availability and descriptions

Use `provided(...)` and `requires(...)` to expose a tool only when its
dependency is present (and, optionally, satisfies a predicate). Predicates
compose with `&`, `|`, and `~`:

```python
from toolbox import provided, requires


@toolbox.tool(
    "Issue a refund (admin only).",
    available_when=provided(BillingClient)
    & requires(UserInfo, predicate=lambda user: user.is_admin),
)
def refund(order_id: str, amount: float) -> str: ...
```

Use `description_from_context(...)` when a tool's description itself should
depend on context (e.g. embedding a resolved account name), with a fallback
for when the dependency isn't provided:

```python
from toolbox import description_from_context

description = description_from_context(
    BankingClient,
    render=lambda client: f"Look up the balance for {client.account_name}.",
    fallback="Look up account balance.",
)


@toolbox.tool(description)
def balance() -> float: ...
```

## Middleware

`Toolbox` never installs middleware implicitly. Tool resolution and argument
validation are core execution mechanics performed when the middleware chain
invokes the call. With `Toolbox()` alone, execution exceptions propagate
normally.

List every middleware an agent loop should use explicitly. For example, this
enables the provided error boundary, call logging, and a timeout:

```python
from toolbox import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    ToolCall,
    ToolMiddleware,
)


class TimeoutMiddleware(ToolMiddleware):
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    async def __call__(self, call: ToolCall, next):
        return await asyncio.wait_for(next(call), timeout=self._seconds)


toolbox = Toolbox(
    middleware=(
        ErrorBoundaryMiddleware(),
        CallLoggingMiddleware(),
        TimeoutMiddleware(5.0),
    ),
)
```

Custom middleware receives the raw `ToolCall` and wraps resolution, validation,
dependency injection, and execution through `next(call)`. `call.raw_args`
contains the model-provided arguments; `call.tool` contains the registered tool
when the name exists. This keeps every execution stage inside the explicit
chain, allowing an installed error boundary to translate any failure for the
agent.

## Merging registries

Combine tools from multiple `Toolbox` instances — e.g. when composing a
registry from several feature modules:

```python
toolbox.merge(other_tools)                # raises on name collisions
toolbox.merge(other_tools, replace=True)  # other_tools wins on collisions
```

## Putting it together

The pieces above compose without knowing about each other. A realistic setup
combines a Pydantic parameter model, an injected client, tool metadata, and an
explicit middleware chain:

```python
from pydantic import BaseModel, Field

from toolbox import (
    CallLoggingMiddleware,
    DependencyProvider,
    ErrorBoundaryMiddleware,
    Inject,
    Toolbox,
    provide,
)


class SearchParams(BaseModel):
    query: str = Field(description="What to search for")
    limit: int = Field(default=5, ge=1, le=20)


class Dependencies(DependencyProvider):
    @provide
    def search_client(self) -> SearchClient:
        return SearchClient()


toolbox = Toolbox(
    dependencies=[Dependencies()],
    middleware=(
        ErrorBoundaryMiddleware(),
        CallLoggingMiddleware(),
    ),
)


@toolbox.tool("Search the connected knowledge base.")
async def search(params: SearchParams, client: Inject[SearchClient]) -> list[str]:
    return await client.search(params.query, params.limit)


schema = toolbox.to_anthropic()
result: object = await toolbox.execute(
    "search", {"query": "tool middleware"}
)
```

Here the application explicitly enables error handling and call logging. An
unknown tool name, invalid arguments, or an exception inside the tool then
comes back as an agent-readable `"Tool failed: ..."` string, while the full
exception is logged.

## Features

The complete list of what the toolkit provides:

- Registration through a `@toolbox.tool` decorator — no hand-written JSON
  Schema, for either plain function signatures or Pydantic models.
- Runtime metadata (`tags`, custom fields) and a `requires_approval` flag,
  kept out of the model-facing schema but readable by the host loop that
  dispatches calls.
- Singleton dependency injection (`Inject[T]`) with validated dependency
  graphs and application-owned resource lifecycles.
- Conditional tool availability and dynamic, context-aware descriptions.
- Sync and async tool execution behind a single async API.
- A composable, opt-in middleware pipeline with provided error-boundary and
  logging middleware; no middleware is installed implicitly.
- Thin, dependency-free schema adapters for OpenAI and Anthropic tool-call
  formats.
- Tool implementations return their natural Python values; the execution
  pipeline does not impose an application-specific result envelope.

## Development

Install the locked development environment and run all quality checks:

```console
uv sync --locked
uv run --locked ruff check .
uv run --locked pytest
```

The test command measures branch coverage for `toolbox` and fails
below 90%. Dependabot groups Python dependency updates into one weekly pull
request; the same CI matrix validates every update on Python 3.13 and 3.14.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution workflow
and conventions.

## License

MIT — see [LICENSE.md](LICENSE.md).
