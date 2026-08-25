# agenttoolkit

`agenttoolkit` provides one provider-neutral definition for tools exposed to
LLM agents. Define a tool once — schema, availability, metadata, and
execution logic — and expose it to OpenAI, Anthropic, or any other provider
without duplicating definitions.

It intentionally contains no application-specific tools and no agent loop:
it is a building block, not a framework.

## Table of contents

- [Installation](#installation)
- [Quickstart](#quickstart)
- [Defining tools](#defining-tools)
- [Grouping tools in plugins](#grouping-tools-in-plugins)
- [Tool metadata](#tool-metadata)
- [Driving an agent loop](#driving-an-agent-loop)
- [Results and errors](#results-and-errors)
- [Dependency injection](#dependency-injection)
- [Conditional availability and descriptions](#conditional-availability-and-descriptions)
- [Middleware](#middleware)
- [Structured-output tools](#structured-output-tools)
- [Merging registries](#merging-registries)
- [Putting it together](#putting-it-together)
- [Filesystem and shell primitives](#filesystem-and-shell-primitives)
- [Skills](#skills)
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
from agenttoolkit import Tools, ToolSchemaFormat

tools = Tools()


@tools.tool("Add two integers.")
def add(a: int, b: int) -> int:
    return a + b


# 1. Send the schema to the model.
schema = tools.get_schema(ToolSchemaFormat.ANTHROPIC)

# 2. The model asks to call "add" with {"a": 2, "b": 3}.
result = await tools.execute("add", {"a": 2, "b": 3})  # 5

# 3. Serialize the value and feed it back to the model.
```

That is the whole core loop. Everything below is optional and independent:
add only the pieces an application actually needs.

## Defining tools

The `@tools.tool(...)` decorator is the entire surface most code touches.
Parameters and their JSON Schema come from the function signature:

```python
@tools.tool("Add two integers.")
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


@tools.tool("Search the connected knowledge base.")
async def search(params: SearchParams) -> list[str]:
    return await run_search(params.query, params.limit)
```

Tools may be synchronous or asynchronous; both run behind the same async API.

Use `tools.register(tool)` when you already have a `Tool` object and want to
register it imperatively. Pass `replace=True` to replace a tool with the same
name.

## Grouping tools in plugins

For larger applications, group related tools in a class and inject stable
application services through its constructor. The module-level `@tool`
decorator marks methods without registering them; `add_plugin` registers all
marked methods together:

```python
from agenttoolkit import Inject, Tools, tool


class CatalogPlugin:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    @tool("Search the product catalog")
    async def search(self, query: str, limit: int = 10) -> list[Product]:
        return await self._catalog.search(query, limit=limit)

    @tool("Compare products for the current user")
    async def compare(
        self,
        product_ids: list[str],
        user: Inject[CurrentUser],
    ) -> Comparison:
        return await self._catalog.compare(product_ids, user=user)

    def normalize(self, query: str) -> str:
        # Undecorated methods are never exposed to the model.
        return " ".join(query.split())


tools = Tools()
tools.add_plugin(CatalogPlugin(catalog_service), name="catalog")
```

The plugin name namespaces every exposed method: the example registers
`catalog_search` and `catalog_compare`. Each registered descriptor retains its
`plugin_name` and local `local_name`. Constructor dependencies belong to the
plugin's lifetime; request-, turn-, or call-scoped dependencies remain
`Inject[T]` parameters on individual methods.

Plugin registration is atomic. Invalid methods or name collisions leave the
registry unchanged. Version 1 accepts constructed instances; applications may
use any DI framework at their composition root. See the runnable
[`class_based_plugins.py`](examples/class_based_plugins.py) example for the
complete setup, including a call-scoped dependency.

## Tool metadata

A tool can carry information for the host loop that dispatches the call.
None of it is visible to the model — it never appears in the generated JSON
Schema:

```python
@tools.tool(
    "Issue a refund for an order.",
    status=lambda params: (
        f"Refunding {params.amount} for order {params.order_id}..."
    ),
    tags=["billing", "write"],
    requires_approval=True,
    metadata={"owner": "billing-team"},
)
def refund(params: RefundParams) -> str: ...
```

- `status` — a human-readable status message, either a plain string or a
  callable taking the parsed params. Prefer a callable: the parameter type
  is inferred from `params`, giving type checking and IDE navigation.
  Render it with `tool.format_status(args)`.
- `tags` — a `frozenset[str]` for grouping or filtering tools, readable as
  `tool.tags`.
- `metadata` — an arbitrary read-only mapping for anything else the host
  application needs, readable as `tool.extra`.
- `requires_approval` — readable as `tool.requires_approval`; check it
  before calling `tools.execute(...)` if the call needs user confirmation
  first. `agenttoolkit` does not enforce approval itself.

```python
tool = tools.get("refund")
tool.tags                # frozenset({"billing", "write"})
tool.extra["owner"]      # "billing-team"
tool.requires_approval   # True
tool.format_status({"order_id": "o-123", "amount": 20.0})
# "Refunding 20.0 for order o-123..."
```

## Driving an agent loop

`Tools.get_schema(...)` returns the schema for every tool available in the
active (or a given) context; `Tools.execute(...)` dispatches a model-produced
call:

```python
openai_schemas = tools.get_schema(ToolSchemaFormat.OPENAI)
anthropic_schemas = tools.get_schema(ToolSchemaFormat.ANTHROPIC)

result = await tools.execute("search", {"query": "tool middleware"}, context=context)
```

Code that only registers or executes tools, independent of how they are shown
to a model, can accept the shared `ToolRegistry` type.

A typical loop confirms approval-gated tools before executing, and reports
status while a call is in flight:

```python
tool = tools.get(name)
if tool is not None and tool.requires_approval and not confirm(name, arguments):
    result = "Tool failed: Declined by user"
else:
    print(tool.format_status(arguments) if tool else name)
    result = await tools.execute(name, arguments, context=context)
```

Iterating a `Tools` instance yields the underlying `Tool` objects — every
registered one, gated or not. Filter with `tool.is_available(context)` to print
a catalog of what a given context actually exposes (`tool.name`,
`tool.resolve_description(context)`, `tool.tags`, ...).

## Results and errors

Tool functions return their natural Python value: text, numbers, collections,
Pydantic models, or `None`. `Tools.execute()` passes that value through
unchanged:

```python
class WeatherResult(BaseModel):
    city: str
    temp_c: float


@tools.tool("Get the current weather for a known city")
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
return types, the static return type of `Tools.execute()` is `object`. The
application's provider adapter owns serialization and can add any
provider-specific metadata at that boundary.

## Dependency injection

A tool that needs a client, a session, or a connection declares it as an
`Inject[T]` parameter. Such parameters are resolved at execution time and
never appear in the model-facing schema:

```python
from agenttoolkit import DependencyProvider, Inject, Tools, provide


class Dependencies(DependencyProvider):
    @provide
    def client(self) -> SearchClient:
        return SearchClient()


tools = Tools(dependencies=[Dependencies()])


@tools.tool("Search the connected knowledge base.")
async def search(query: str, client: Inject[SearchClient]) -> list[str]:
    return await client.search(query)
```

Dependencies are declared on `DependencyProvider` classes. The container
validates missing definitions, duplicates, cycles, and invalid lifetime
relationships when it is constructed.

Each dependency also has a lifetime, given by its scope:

```python
from collections.abc import AsyncIterator

from agenttoolkit import DependencyProvider, Scope, provide


class Dependencies(DependencyProvider):
    @provide(scope=Scope.APP)
    def client(self) -> SearchClient:
        return SearchClient()

    @provide(scope=Scope.TURN)
    def turn_state(self) -> TurnState:
        return TurnState()

    @provide  # CALL is the default
    async def connection(self) -> AsyncIterator[Connection]:
        connection = await connect()
        try:
            yield connection
        finally:
            await connection.close()
```

`APP` lives for the tools context, `TURN` is opened explicitly around an
agent turn, and `CALL` is opened automatically by `tools.execute()`:

```python
async with tools:
    async with tools.scope(Scope.TURN):
        await tools.execute("search", {"query": "dependency injection"})
```

A tool that needs a `TURN` dependency fails clearly when no turn scope is
active. Factory methods may be synchronous, asynchronous, generators, or
async generators. Generator cleanup runs when its owning scope exits, even
after an error. `Tools` creates and owns the dependency container internally.

## Conditional availability and descriptions

Use `provided(...)` and `requires(...)` to expose a tool only when its
dependency is present (and, optionally, satisfies a predicate). Predicates
compose with `&`, `|`, and `~`:

```python
from agenttoolkit import provided, requires


@tools.tool(
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
from agenttoolkit import description_from_context

description = description_from_context(
    BankingClient,
    render=lambda client: f"Look up the balance for {client.account_name}.",
    fallback="Look up account balance.",
)


@tools.tool(description)
def balance() -> float: ...
```

## Middleware

`Tools` never installs middleware implicitly. Tool resolution and argument
validation are core execution mechanics performed when the middleware chain
invokes the call. With `Tools()` alone, execution exceptions propagate
normally.

List every middleware an agent loop should use explicitly. For example, this
enables the provided error boundary, call logging, and a timeout:

```python
from agenttoolkit import (
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


tools = Tools(
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

## Structured-output tools

Some providers select a tool by asking the model for a structured response
rather than a provider-specific tool call. Use `StructuredOutputTools` in
that case. It creates one Pydantic model per available tool, so the model
can choose a tool while also returning fields shared by every response.

This is useful when a tool call has to travel together with additional
output — the model's reasoning, a summary of the state it observed, or a
request identifier:

```python
from pydantic import BaseModel, Field

from agenttoolkit import StructuredOutputTools


class AgentResponse(BaseModel):
    reasoning: str = Field(description="Why this tool is the next step")
    state_summary: str = Field(description="What the model observed so far")


tools = StructuredOutputTools()


@tools.tool("Search the connected knowledge base.")
async def search(query: str) -> list[str]: ...


[SearchTool] = tools.create_tool_models(base_model=AgentResponse)

# Give SearchTool to the LLM as its structured-output model.
response = SearchTool.model_validate(
    {
        "reasoning": "The knowledge base has not been consulted yet.",
        "state_summary": "No results collected so far.",
        "search": {"query": "tool middleware"},
    }
)
await tools.execute("search", response.search.model_dump())
```

`create_tool_models()` returns only tools available in the active context.
Pass `include_tools=[...]` to limit the choices, or `context=...` to derive
them for a particular request. `StructuredOutputTools` shares registration,
availability, middleware, execution, and merging with `Tools`; it differs
only in how tools are presented to the model.

## Merging registries

Combine tools from multiple `ToolRegistry` instances — e.g. when composing a
registry from several feature modules:

```python
tools.merge(other_tools)               # raises on name collisions
tools.merge(other_tools, replace=True)  # other_tools wins on collisions
```

## Putting it together

The pieces above compose without knowing about each other. A realistic setup
combines a Pydantic parameter model, an injected client, tool metadata, and an
explicit middleware chain:

```python
from pydantic import BaseModel, Field

from agenttoolkit import (
    CallLoggingMiddleware,
    DependencyProvider,
    ErrorBoundaryMiddleware,
    Inject,
    Scope,
    Tools,
    ToolSchemaFormat,
    provide,
)


class SearchParams(BaseModel):
    query: str = Field(description="What to search for")
    limit: int = Field(default=5, ge=1, le=20)


class Dependencies(DependencyProvider):
    @provide(scope=Scope.APP)
    def search_client(self) -> SearchClient:
        return SearchClient()


tools = Tools(
    dependencies=[Dependencies()],
    middleware=(
        ErrorBoundaryMiddleware(),
        CallLoggingMiddleware(),
    ),
)


@tools.tool(
    "Search the connected knowledge base.",
    status=lambda params: f"Searching for {params.query}...",
)
async def search(params: SearchParams, client: Inject[SearchClient]) -> list[str]:
    return await client.search(params.query, params.limit)


async with tools:
    schema = tools.get_schema(ToolSchemaFormat.ANTHROPIC)

    async with tools.scope(Scope.TURN):
        result: object = await tools.execute(
            "search", {"query": "tool middleware"}
        )
```

Here the application explicitly enables error handling and call logging. An
unknown tool name, invalid arguments, or an exception inside the tool then
comes back as an agent-readable `"Tool failed: ..."` string, while the full
exception is logged.

## Filesystem and shell primitives

`agenttoolkit.builtins` contains raw async implementations rather than a
predefined set of model-facing tools. Applications can use them directly,
inject them through `ToolContext`, or expose only the operations appropriate
for a particular agent.

```python
from pathlib import Path

from agenttoolkit.builtins import (
    BindMount,
    CommandDefaults,
    DockerSandbox,
    LocalWorkspace,
    SandboxPolicy,
)

workspace = LocalWorkspace("./project")
await workspace.write_file("src/example.py", "print('hello')\n")

entries = await workspace.list_dir("src")
source = await workspace.read_file(entries[0].path)

output = workspace.root / "output"
output.mkdir(exist_ok=True)
cli_config = Path.home() / ".config" / "my-cli"

policy = SandboxPolicy.for_workspace(
    workspace.root,
    writable=True,
    enable_network_access=True,
)
sandbox = DockerSandbox(
    "my-cli:latest",
    defaults=CommandDefaults(working_directory=workspace.root),
    policy=policy,
    inherit_environment=("MY_CLI_TOKEN",),
    mounts=(
        BindMount.read_only(cli_config, "/home/agent/.config/my-cli"),
        BindMount.read_write(output, "/output"),
    ),
    user="host",
)
async with sandbox:
    result = await sandbox.execute("my-cli build --output /output")
```

The `Workspace` port provides `read_file`, `write_file`, `edit_file`, `glob`,
`list_dir`, and `stat`. Exploration returns `Entry` values with a root-relative
POSIX path, directory and symlink flags, size, and modification time. Local
reads and writes are confined to the workspace root and bounded by a
configurable file-size limit.

The `CommandRunner` port returns a common `CommandResult` from local and
isolated backends. `CommandDefaults` configures the working directory,
environment, timeout, and captured-output limit. `SandboxPolicy` is separate
and contains only isolation requirements: readable and writable paths, network
access, memory, process, and CPU limits. A sandbox backend must enforce every
requested isolation setting or reject it.

Only backends that own persistent resources expose a lifecycle.
`DockerSandbox` supports `open()`/`close()` and `async with`, starts one
container, tunnels every command through `docker exec`, and removes the
container afterwards. This preserves container state and avoids paying
container startup latency for every command.
If a Docker command times out, the sandbox removes the container to guarantee
that no detached process keeps running; call `open()` again before continuing.

`DockerSandbox` enforces all sandbox resource limits. `BubblewrapSandbox`
supports filesystem and network isolation and rejects unsupported resource
limits. `LocalShellRunner` executes trusted commands directly and accepts no
`SandboxPolicy`, so it makes no isolation claim.

`DockerSandbox` also supports named bind mounts and an explicit allowlist of
host environment variables. `BindMount.read_write(...)` writes directly back
to the host. `inherit_environment` fails fast when a requested variable is
missing and forwards its name without embedding the secret value in the
generated Docker arguments. On POSIX hosts, `user="host"` maps the container
process to the host UID and GID so generated files remain owned by the
developer. Use `environment={...}` on `CommandDefaults` or `env={...}` on
`execute(...)` for explicit values and per-call overrides.

## Skills

Local Agent Skills are discovered from directories containing one
subdirectory per skill, each with a `SKILL.md` file using YAML frontmatter
(`name`, `description`, and optional `license`, `compatibility`, `metadata`,
`allowed-tools`) followed by Markdown instructions:

```
skills/
  internet-research/
    SKILL.md
    references/
      guide.md
    scripts/
      search.py
```

`name` must be 1–64 lowercase letters, numbers, or hyphens, and must match
its parent directory name.

```python
from agenttoolkit import Skills

skills = Skills.from_dir("./skills")

# Render the compact skill listing for the agent's system prompt.
system_prompt = f"You are helpful.\n\n{skills.render_prompt()}"

# Progressive loading returns full instructions and relative resource paths.
loaded = skills.load("internet-research")
system_prompt += f"\n\n{loaded.instructions}"

# Re-scan the configured directories after skills are added or removed.
changes = skills.refresh()
print(changes.added, changes.updated, changes.removed)

# The application decides which general filesystem and process tools to expose.
guide = read_file(loaded.directory / "references/guide.md")
output = await run_process(
    ["python", "scripts/search.py", "python packaging"],
    cwd=loaded.directory,
)
```

`Skills.from_dir` accepts multiple directories; a skill discovered
later overrides one with the same name from an earlier directory (logged as
a warning). `SKILL.md` is re-parsed from disk on each `load`, so instructions
can be edited without restarting the process. `refresh()` rebuilds the registry
from the configured directories, picking up added, changed, and removed skills.
If discovery fails, the previous registry remains available.

`refresh()` returns an immutable `SkillChanges` value containing the registry
revision and the added, updated, and removed skill names. `refresh_if_changed()`
first compares a lightweight fingerprint of the `SKILL.md` paths, modification
times, and sizes, avoiding parsing when no skill document changed.

Agents that can write their own skills can attach `SkillRefreshMiddleware`.
By default it checks the registry after every tool call, silently and without
touching the tool's own result. The check uses a lightweight fingerprint, so
unchanged skill documents are not reparsed:

```python
from agenttoolkit import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    SkillRefreshMiddleware,
)

tools = Tools(
    context=ToolContext(skills),
    middleware=(
        ErrorBoundaryMiddleware(),
        CallLoggingMiddleware(),
        SkillRefreshMiddleware(),
    ),
)
```

The registry is resolved from the call's `ToolContext`, not captured at
construction — a per-call `context=` argument refreshes the registry
actually in use, and the
middleware is a no-op when the context holds no `Skills`.

Invalid skill edits are not activated and
the previous registry remains available. Applications that embed
`skills.render_prompt()` in model context should render that dynamic portion
again before each model invocation.

`load()` returns an immutable `LoadedSkill` containing `name`, `instructions`,
the absolute skill `directory`, and sorted relative `resources`. Resource
reading, process execution, timeouts, sandboxing, and permissions deliberately
belong to the application's general filesystem and process tools instead of
the Skills API. Skill directories and their scripts must still be treated as
trusted code.

## Features

The complete list of what the toolkit provides:

- Registration through a `@tools.tool` decorator — no hand-written JSON
  Schema, for either plain function signatures or Pydantic models.
- Runtime metadata (`effects`, `status`, `tags`, custom fields) and an
  `requires_approval` flag, kept out of the model-facing schema but readable
  by the host loop that dispatches calls.
- Scoped dependency injection (`Inject[T]`) with validated dependency graphs,
  lifecycle hooks, and `APP`, `TURN`, and `CALL` lifetimes.
- Conditional tool availability and dynamic, context-aware descriptions.
- Sync and async tool execution behind a single async API.
- A composable, opt-in middleware pipeline with provided error-boundary and
  logging middleware; no middleware is installed implicitly.
- Thin, dependency-free schema adapters for OpenAI and Anthropic tool-call
  formats.
- A separate structured-output registry that creates Pydantic tool models
  without adding that interface to schema-based tools.
- Tool implementations return their natural Python values; the execution
  pipeline does not impose an application-specific result envelope.
- Async filesystem and shell ports with local, Docker, and Bubblewrap
  implementations for common agent capabilities.
- Local Agent Skills discovery and progressive loading, compatible with the
  `SKILL.md` convention.

## Development

Install the locked development environment and run all quality checks:

```console
uv sync --locked
uv run --locked ruff check .
uv run --locked pytest
```

The test command measures branch coverage for `agenttoolkit` and fails
below 90%. Dependabot groups Python dependency updates into one weekly pull
request; the same CI matrix validates every update on Python 3.13 and 3.14.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution workflow
and conventions.

## License

MIT — see [LICENSE.md](LICENSE.md).
