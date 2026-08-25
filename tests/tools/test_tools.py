import logging
from typing import Annotated

import pytest
from pydantic import BaseModel, Field, ValidationError

from agenttoolkit import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    Inject,
    StructuredOutputTools,
    ToolContext,
    Tools,
    ToolSchemaFormat,
    description_from_context,
    provided,
)


class SearchParams(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, ge=1)


class SearchClient:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix


@pytest.mark.asyncio
async def test_register_validate_inject_and_execute() -> None:
    client = SearchClient("found:")
    tools = Tools(context=ToolContext(client))

    @tools.register(
        "Search",
        params=SearchParams,
        tags=["network"],
        metadata={"owner": "knowledge"},
    )
    async def search(
        params: SearchParams,
        dependency: Inject[SearchClient],
    ) -> str:
        return f"{dependency.prefix}{params.query}:{params.limit}"

    result = await tools.execute("search", {"query": "docs"})
    tool = tools.get("search")

    assert result == "found:docs:10"
    assert tool is not None
    assert tool.tags == frozenset({"network"})
    assert tool.extra["owner"] == "knowledge"


@pytest.mark.asyncio
async def test_plain_signature_is_validated_and_sync_result_is_returned() -> None:
    tools = Tools(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    @tools.register("Add numbers")
    def add(a: int, b: int = 1) -> int:
        return a + b

    assert await tools.execute("add", {"a": "2"}) == 3

    invalid = await tools.execute("add", {})
    assert isinstance(invalid, str)
    assert invalid.startswith("Tool failed: ")
    assert "a" in invalid


def test_schema_is_provider_neutral_with_adapters() -> None:
    tools = Tools()

    @tools.register("Search", params=SearchParams)
    def search(params: SearchParams) -> None:
        pass

    native = tools.get_schema()[0]
    openai = tools.get_schema(ToolSchemaFormat.OPENAI)[0]
    anthropic = tools.get_schema(ToolSchemaFormat.ANTHROPIC)[0]

    assert native.parameters["properties"]["query"]["description"] == "Search query"
    assert openai["type"] == "function"
    assert openai["function"]["name"] == "search"
    assert anthropic["input_schema"] == native.parameters
    assert tools.get("search").to_openai_schema() == openai
    assert tools.get("search").parse_arguments('{"query": "docs"}') == {
        "query": "docs",
        "limit": 10,
    }


def test_annotated_description_is_included_in_callable_schema() -> None:
    tools = Tools()

    @tools.register("Greet")
    def greet(name: Annotated[str, "Person to greet"]) -> None:
        pass

    parameters = tools.get_schema()[0].parameters
    assert parameters["properties"]["name"]["description"] == "Person to greet"


def test_tool_models_support_structured_output_and_a_custom_base() -> None:
    class StructuredResponse(BaseModel):
        request_id: str = "generated"

    tools = StructuredOutputTools()

    @tools.register("Search the documentation", params=SearchParams)
    def search(params: SearchParams) -> None:
        pass

    @tools.register("Do nothing")
    def noop() -> None:
        pass

    models = tools.create_tool_models(
        ["search"],
        base_model=StructuredResponse,
    )

    assert len(models) == 1
    assert issubclass(models[0], StructuredResponse)
    response = models[0].model_validate({"search": {"query": "tools"}})
    assert response.request_id == "generated"
    assert response.search == SearchParams(query="tools")
    assert models[0].model_json_schema()["properties"]["search"]["description"] == (
        "Search the documentation"
    )

    with pytest.raises(ValidationError, match="extra_forbidden"):
        models[0].model_validate({"search": {"query": "tools"}, "unexpected": True})


def test_tool_models_respect_contextual_availability() -> None:
    tools = StructuredOutputTools()

    @tools.register("Search", available_when=provided(SearchClient))
    def search(query: str) -> None:
        pass

    assert tools.create_tool_models() == []
    models = tools.create_tool_models(context=ToolContext(SearchClient()))
    assert [model.__name__ for model in models] == ["SearchTool"]


def test_tool_representations_expose_only_their_own_interface() -> None:
    assert not hasattr(Tools(), "create_tool_models")
    assert not hasattr(StructuredOutputTools(), "get_schema")


def test_context_controls_availability_and_description() -> None:
    tools = Tools()

    @tools.register(
        description_from_context(
            SearchClient,
            render=lambda client: f"Search with prefix {client.prefix}",
            fallback="Search",
        ),
        available_when=provided(SearchClient),
    )
    def search(query: str) -> None:
        pass

    tool = tools.get("search")
    assert tool is not None
    assert tool.resolve_description() == "Search"
    assert tools.get_schema() == []

    schemas = tools.get_schema(context=ToolContext(SearchClient("kb:")))
    assert schemas[0].description == "Search with prefix kb:"


@pytest.mark.asyncio
async def test_tool_errors_are_logged_and_returned_by_the_boundary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tools = Tools(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    @tools.register("Fail internally")
    def internal_failure() -> None:
        raise RuntimeError("secret")

    with caplog.at_level(logging.ERROR, logger="agenttoolkit.tools.middleware"):
        result = await tools.execute("internal_failure")

    assert "Tool 'internal_failure' failed" in caplog.text
    assert result == "Tool failed: secret"


@pytest.mark.asyncio
async def test_tools_do_not_install_an_error_boundary_by_default() -> None:
    tools = Tools()

    @tools.register("Fail internally")
    def internal_failure() -> None:
        raise RuntimeError("secret")

    with pytest.raises(RuntimeError, match="secret"):
        await tools.execute("internal_failure")


def test_duplicate_registration_and_status_validation() -> None:
    tools = Tools()

    @tools.register("First")
    def duplicate() -> None:
        pass

    with pytest.raises(ValueError, match="already registered"):

        @tools.register("Second")
        def duplicate() -> None:
            pass
