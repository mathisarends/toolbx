from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import BaseModel

from toolbox import (
    Tool,
    Toolbox,
    ToolCall,
    ToolMetadata,
    ToolMiddleware,
    Toolset,
    build_schema,
)
from toolbox import tool as mark_tool


class Service:
    def __init__(self, name: str, *, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled


class OtherService:
    pass


class ItemParams(BaseModel):
    item: str
    count: int | None = None


class RecordingMiddleware(ToolMiddleware):
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __call__(
        self, call: ToolCall, call_next: Callable[[ToolCall], Awaitable[object]]
    ) -> object:
        self.events.append(f"before:{call.raw_args.get('value')}")
        result = await call_next(call)
        self.events.append(f"after:{result}")
        return result


@pytest.mark.asyncio
async def test_custom_middleware_wraps_execution() -> None:
    events: list[str] = []
    toolbox = Toolbox(middleware=[RecordingMiddleware(events)])

    class DefinedTools1(Toolset, namespace=None):
        @mark_tool("Double a number")
        def double(self, value: int) -> int:
            return value * 2

    toolbox.add(DefinedTools1())
    result = await toolbox.execute("double", {"value": "3"})
    assert result == 6
    assert events[0] == "before:3"
    assert events[1] == "after:6"


@pytest.mark.asyncio
async def test_structured_tool_results_pass_through_unchanged() -> None:
    toolbox = Toolbox()
    payload: dict[str, object] = {"value": 6, "citations": ["doc-1"]}

    class DefinedTools2(Toolset, namespace=None):
        @mark_tool("Return structured data")
        def structured(self) -> dict[str, object]:
            return payload

    toolbox.add(DefinedTools2())
    assert await toolbox.execute("structured") is payload


def test_registry_merge_iteration_and_replacement_are_explicit() -> None:
    first = Toolbox()
    second = Toolbox()

    class DefinedTools3(Toolset, namespace=None):
        @mark_tool("Old implementation", name="shared")
        def old(self) -> str:
            return "old"

    first.add(DefinedTools3())

    class DefinedTools4(Toolset, namespace=None):
        @mark_tool("New implementation", name="shared")
        def new(self) -> str:
            return "new"

    second.add(DefinedTools4())
    with pytest.raises(ValueError, match="already registered"):
        first.merge(second)
    first.merge(second, replace=True)
    assert len(first) == 1
    assert next(iter(first)).description == "New implementation"


def test_tool_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        Tool("", "Missing name", lambda: None)


def test_tools_can_declare_approval_requirement() -> None:
    tool = Tool("safe", "Safe action", lambda: None)
    toolbox = Toolbox()
    assert tool.requires_approval is False

    class DefinedTools5(Toolset, namespace=None):
        @mark_tool("Sensitive action", requires_approval=True)
        def sensitive(self) -> None:
            pass

    toolbox.add(DefinedTools5())
    assert toolbox.get("sensitive").requires_approval is True


def test_metadata_is_defensively_copied_and_immutable() -> None:
    tags = {"read"}
    extra: dict[str, Any] = {"owner": "platform"}
    metadata = ToolMetadata(tags=tags, extra=extra)
    tags.add("write")
    extra["owner"] = "changed"
    assert metadata.tags == frozenset({"read"})
    assert metadata.extra == {"owner": "platform"}
    with pytest.raises(TypeError):
        metadata.extra["owner"] = "changed"


def test_callable_schema_rejects_variadics_and_requires_input() -> None:

    def variadic(*values: str) -> None:
        pass

    with pytest.raises(TypeError, match="cannot use variadic parameters"):
        build_schema(variadic)
    with pytest.raises(ValueError, match="callable or param_model"):
        build_schema()

    def variadic_model(params: ItemParams, *values: str) -> None:
        pass

    with pytest.raises(TypeError, match="cannot use variadic parameters"):
        Tool("variadic_model", "Variadic model", variadic_model)


def test_param_model_binding_must_be_unambiguous_at_class_definition() -> None:
    with pytest.raises(ValueError, match="unambiguous"):

        class Invalid(Toolset):
            @mark_tool("Ambiguous", params=ItemParams)
            def ambiguous(self, first: object, second: object) -> None:
                pass
