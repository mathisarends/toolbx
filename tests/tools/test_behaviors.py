from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import BaseModel

from toolbox import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    Inject,
    Tool,
    Toolbox,
    ToolCall,
    ToolContext,
    ToolMetadata,
    ToolMiddleware,
    build_schema,
    provided,
    requires,
)


class Service:
    def __init__(self, name: str, *, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled


class OtherService:
    pass


class ItemParams(BaseModel):
    item: str
    count: int | None = None


def test_context_prefers_latest_dependency_and_supports_lifecycle() -> None:
    first = Service("first")
    latest = Service("latest")
    other = OtherService()
    context = ToolContext(None, first).provide(other, None, latest)

    assert len(context) == 3
    assert context.resolve(Service) is latest
    assert context.resolve(OtherService) is other
    assert context.without(Service) is context
    assert context.resolve(Service) is None
    assert context.clear() is context
    assert len(context) == 0


def test_availability_predicates_can_be_composed() -> None:
    enabled = ToolContext(Service("enabled"))
    disabled = ToolContext(Service("disabled", enabled=False))
    has_service = provided(Service)
    is_enabled = requires(Service, predicate=lambda service: service.enabled)

    assert (has_service & is_enabled)(enabled)
    assert not (has_service & is_enabled)(disabled)
    assert (provided(OtherService) | is_enabled)(enabled)
    assert (~has_service)(None)
    assert not is_enabled(None)


@pytest.mark.asyncio
async def test_optional_injected_dependency_uses_function_default() -> None:
    toolbox = Toolbox()

    @toolbox.tool("Identify the configured service")
    def identify(service: Inject[Service] = None) -> str:
        return "default" if service is None else service.name

    assert await toolbox.execute("identify") == "default"
    assert (
        await toolbox.execute(
            "identify",
            context=ToolContext(Service("injected")),
        )
        == "injected"
    )


@pytest.mark.asyncio
async def test_missing_required_injection_is_returned_as_failure() -> None:
    toolbox = Toolbox(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    @toolbox.tool("Use a required service")
    def identify(service: Inject[Service]) -> str:
        return service.name

    result = await toolbox.execute("identify")

    assert result == (
        "Tool failed: Missing injected dependency for parameter 'service' "
        "of type 'Service'"
    )


@pytest.mark.asyncio
async def test_unavailable_and_unknown_tools_report_available_names() -> None:
    toolbox = Toolbox(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    @toolbox.tool("Always available")
    def public() -> None:
        pass

    @toolbox.tool("Requires a service", available_when=provided(Service))
    def private() -> None:
        pass

    unavailable = await toolbox.execute("private")
    unknown = await toolbox.execute("missing")

    assert unavailable == ("Tool failed: Unknown tool 'private'. Available: ['public']")
    assert unknown == "Tool failed: Unknown tool 'missing'. Available: ['public']"


class RecordingMiddleware(ToolMiddleware):
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __call__(
        self,
        call: ToolCall,
        next: Callable[
            [ToolCall],
            Awaitable[object],
        ],
    ) -> object:
        self.events.append(f"before:{call.raw_args.get('value')}")
        result = await next(call)
        self.events.append(f"after:{result}")
        return result


@pytest.mark.asyncio
async def test_custom_middleware_wraps_execution() -> None:
    events: list[str] = []
    toolbox = Toolbox(middleware=[RecordingMiddleware(events)])

    @toolbox.tool("Double a number")
    def double(value: int) -> int:
        return value * 2

    result = await toolbox.execute("double", {"value": "3"})

    assert result == 6
    assert events[0] == "before:3"
    assert events[1] == "after:6"


@pytest.mark.asyncio
async def test_structured_tool_results_pass_through_unchanged() -> None:
    toolbox = Toolbox()
    payload: dict[str, object] = {"value": 6, "citations": ["doc-1"]}

    @toolbox.tool("Return structured data")
    def structured() -> dict[str, object]:
        return payload

    assert await toolbox.execute("structured") is payload


def test_registry_merge_iteration_and_replacement_are_explicit() -> None:
    first = Toolbox()
    second = Toolbox()

    @first.tool("Old implementation", name="shared")
    def old() -> str:
        return "old"

    @second.tool("New implementation", name="shared")
    def new() -> str:
        return "new"

    with pytest.raises(ValueError, match="already registered"):
        first.merge(second)

    first.merge(second, replace=True)

    assert len(first) == 1
    assert next(iter(first)).description == "New implementation"


def test_per_call_context_does_not_replace_the_registry_context() -> None:
    toolbox = Toolbox(context=ToolContext(Service("registry")))

    @toolbox.tool("Requires a service", available_when=provided(Service))
    def current() -> None:
        pass

    assert [schema.name for schema in toolbox.get_schema()] == ["current"]
    assert toolbox.get_schema(context=ToolContext()) == []
    assert [schema.name for schema in toolbox.get_schema()] == ["current"]

    with pytest.raises(ValueError, match="not a valid ToolSchemaFormat"):
        toolbox.get_schema("invalid")


@pytest.mark.asyncio
async def test_registry_context_can_be_set_after_creation() -> None:
    toolbox = Toolbox()

    @toolbox.tool("Identify the configured service", available_when=provided(Service))
    def identify(service: Inject[Service]) -> str:
        return service.name

    assert toolbox.get_schema() == []

    toolbox.set_context(ToolContext(Service("updated")))

    assert [schema.name for schema in toolbox.get_schema()] == ["identify"]
    assert await toolbox.execute("identify") == "updated"

    toolbox.set_context(None)

    assert toolbox.get_schema() == []


def test_tool_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        Tool("", "Missing name", lambda: None)


def test_tools_can_declare_approval_requirement() -> None:
    tool = Tool("safe", "Safe action", lambda: None)
    toolbox = Toolbox()

    assert tool.requires_approval is False

    @toolbox.tool("Sensitive action", requires_approval=True)
    def sensitive() -> None:
        pass

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


@pytest.mark.asyncio
async def test_param_model_binding_must_be_unambiguous() -> None:
    toolbox = Toolbox(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    @toolbox.tool("Ambiguous", params=ItemParams)
    def ambiguous(first: object, second: object) -> None:
        pass

    result = await toolbox.execute("ambiguous", {"item": "document"})

    assert isinstance(result, str)
    assert result.startswith("Tool failed: ")
    assert "unambiguous" in result
