from dataclasses import replace

import pytest
from pydantic import BaseModel, ValidationError

from toolbx import (
    ApprovalMiddleware,
    ErrorBoundaryMiddleware,
    Toolbox,
    ToolRequest,
    Toolset,
    tool,
)


class EchoParams(BaseModel):
    value: int


class EchoTools(Toolset):
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self.enabled = True

    @tool("Echo a value", name="say", available_when=lambda self: self.enabled)
    def echo(self, value: int, suffix: str = "!") -> str:
        return f"{self.prefix}{value}{suffix}"

    @tool("Echo validated params", params=EchoParams)
    async def structured(self, params: EchoParams) -> int:
        assert isinstance(params, EchoParams)
        return params.value

    def helper(self) -> str:
        return "helper"


@pytest.mark.asyncio
async def test_call_resolves_exported_names_and_runs_middleware() -> None:
    seen = []

    async def record(call, call_next):
        seen.append((call.name, call.call_id, call.arguments))
        return await call_next(call)

    tools = EchoTools("docs:")
    toolbox = Toolbox(middleware=[record])
    toolbox.add(tools, namespace="custom")

    assert await toolbox.call(tools.echo, value="7") == "docs:7!"
    assert await toolbox.call(tools.structured, value="8") == 8
    assert seen == [
        ("custom_say", None, {"value": "7"}),
        ("custom_structured", None, {"value": "8"}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["echo", "structured"])
@pytest.mark.parametrize("arguments", [{}, {"value": "invalid"}, {"value": 7, "x": 1}])
async def test_call_validates_arguments(method: str, arguments: dict) -> None:
    tools = EchoTools()
    toolbox = Toolbox(toolsets=(tools,))

    with pytest.raises(ValidationError):
        await toolbox.call(getattr(tools, method), **arguments)


@pytest.mark.asyncio
async def test_call_forwards_keywords_without_reserving_metadata_names() -> None:
    seen = []

    async def record(call, call_next):
        seen.append(call.call_id)
        return await call_next(call)

    class Keywords(Toolset):
        @tool("Echo argument names")
        def echo(
            instance, self: str, method: str, call_id: str, arguments: str
        ) -> tuple:
            return self, method, call_id, arguments

    tools = Keywords()
    toolbox = Toolbox(toolsets=(tools,), middleware=[record])

    assert await toolbox.call(
        tools.echo, self="a", method="b", call_id="c", arguments="d"
    ) == ("a", "b", "c", "d")
    assert seen == [None]


@pytest.mark.asyncio
async def test_call_uses_arguments_changed_by_middleware() -> None:
    async def change(call, call_next):
        return await call_next(replace(call, arguments={"value": 9}))

    tools = EchoTools()
    toolbox = Toolbox(toolsets=(tools,), middleware=[change])

    assert await toolbox.call(tools.echo, value=1) == "9!"


@pytest.mark.asyncio
async def test_call_checks_availability_on_every_invocation() -> None:
    tools = EchoTools()
    toolbox = Toolbox(toolsets=(tools,))

    tools.enabled = False
    with pytest.raises(LookupError, match="Unknown tool 'echo_say'"):
        await toolbox.call(tools.echo, value=1)
    tools.enabled = True
    assert await toolbox.call(tools.echo, value=1) == "1!"
    tools.enabled = False
    with pytest.raises(LookupError):
        await toolbox.call(tools.echo, value=1)
    assert tools.echo(1) == "1!"


@pytest.mark.asyncio
async def test_call_uses_approval_and_error_boundary_middleware() -> None:
    asked = []
    invoked = []

    class Actions(Toolset):
        @tool("Run an action", requires_approval=True)
        def run(self) -> None:
            invoked.append(True)
            raise RuntimeError("failed")

    answer = False

    def confirm(call):
        asked.append(call.name)
        return answer

    actions = Actions()
    toolbox = Toolbox(
        toolsets=(actions,),
        middleware=[ErrorBoundaryMiddleware(), ApprovalMiddleware(confirm)],
    )

    assert await toolbox.call(actions.run) == "Tool call declined by the user"
    assert invoked == []
    answer = True
    assert await toolbox.call(actions.run) == "Tool failed: failed"
    assert invoked == [True]
    assert asked == ["actions_run", "actions_run"]


@pytest.mark.asyncio
async def test_call_rejects_helpers_and_unregistered_instances() -> None:
    tools = EchoTools()
    toolbox = Toolbox(toolsets=(tools,))

    for method in (tools.helper, EchoTools().echo):
        with pytest.raises(LookupError, match="not registered"):
            await toolbox.call(method)


@pytest.mark.asyncio
async def test_call_respects_subset_removal_and_merge_replacement() -> None:
    tools = EchoTools()
    toolbox = Toolbox(toolsets=(tools,))
    subset = toolbox.subset(names=["echo_say"])
    with pytest.raises(LookupError, match="not registered"):
        await subset.call(tools.structured, value=1)
    subset.remove("echo_say")
    with pytest.raises(LookupError, match="not registered"):
        await subset.call(tools.echo, value=1)
    assert await toolbox.call(tools.echo, value=1) == "1!"

    replacement = EchoTools("new:")
    toolbox.merge(Toolbox(toolsets=(replacement,)), replace=True)
    with pytest.raises(LookupError, match="not registered"):
        await toolbox.call(tools.echo, value=1)
    assert await toolbox.call(replacement.echo, value=1) == "new:1!"


@pytest.mark.asyncio
async def test_call_resolves_unhashable_instances_by_identity() -> None:
    class EqualTools(EchoTools):
        def __eq__(self, other: object) -> bool:
            return True

    first = EqualTools("first:")
    second = EqualTools("second:")
    toolbox = Toolbox()
    toolbox.add(first, namespace="first")
    toolbox.add(second, namespace="second")

    assert await toolbox.call(first.echo, value=1) == "first:1!"
    assert await toolbox.call(second.echo, value=1) == "second:1!"


@pytest.mark.asyncio
async def test_call_rejects_ambiguity_and_execute_selects_a_name() -> None:
    tools = EchoTools()
    toolbox = Toolbox(toolsets=(tools,))
    toolbox.add(tools, namespace="alias")

    with pytest.raises(ValueError, match=r"more than once.*echo_say, alias_say"):
        await toolbox.call(tools.echo, value=1)
    assert await toolbox.execute(ToolRequest("echo_say", {"value": 1})) == "1!"
    assert await toolbox.execute(ToolRequest("alias_say", {"value": 2})) == "2!"
    toolbox.remove("alias_say")
    assert await toolbox.call(tools.echo, value=3) == "3!"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", [None, "echo", EchoTools.echo, lambda: None])
async def test_call_requires_a_bound_toolset_method(method) -> None:
    with pytest.raises(TypeError, match="bound Toolset method"):
        await Toolbox().call(method)


@pytest.mark.asyncio
async def test_call_rejects_bound_methods_of_other_objects() -> None:
    class Other:
        def echo(self) -> None:
            pass

    with pytest.raises(TypeError, match="bound Toolset method"):
        await Toolbox().call(Other().echo)


@pytest.mark.asyncio
async def test_execute_requires_a_tool_request() -> None:
    with pytest.raises(TypeError, match="execute expects a ToolRequest"):
        await Toolbox().execute("echo")
