import logging
from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from agenttoolkit import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    Inject,
    Tool,
    Toolbox,
    ToolContext,
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


def test_register_adds_an_existing_tool_imperatively() -> None:
    toolbox = Toolbox()

    def greet(name: str) -> str:
        return f"Hello, {name}"

    tool = Tool(name="greet", description="Greet someone", fn=greet)

    assert toolbox.register(tool) is tool
    assert toolbox.get("greet") is tool
    assert tool.plugin_name is None
    assert tool.local_name is None


@pytest.mark.asyncio
async def test_tool_infers_model_validates_injects_and_executes() -> None:
    client = SearchClient("found:")
    toolbox = Toolbox(context=ToolContext(client))

    @toolbox.tool(
        "Search",
        tags=["network"],
        metadata={"owner": "knowledge"},
    )
    async def search(
        params: SearchParams,
        dependency: Inject[SearchClient],
    ) -> str:
        return f"{dependency.prefix}{params.query}:{params.limit}"

    result = await toolbox.execute("search", {"query": "docs"})
    tool = toolbox.get("search")

    assert result == "found:docs:10"
    assert tool is not None
    assert tool.param_model is SearchParams
    assert tool.tags == frozenset({"network"})
    assert tool.extra["owner"] == "knowledge"


@pytest.mark.asyncio
async def test_plain_signature_is_validated_and_sync_result_is_returned() -> None:
    toolbox = Toolbox(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    @toolbox.tool("Add numbers")
    def add(a: int, b: int = 1) -> int:
        return a + b

    assert await toolbox.execute("add", {"a": "2"}) == 3

    invalid = await toolbox.execute("add", {})
    assert isinstance(invalid, str)
    assert invalid.startswith("Tool failed: ")
    assert "a" in invalid


def test_schema_is_provider_neutral_with_adapters() -> None:
    toolbox = Toolbox()

    @toolbox.tool("Search")
    def search(params: SearchParams) -> None:
        pass

    native = toolbox.get_schema()[0]
    openai = toolbox.get_schema(ToolSchemaFormat.OPENAI)[0]
    anthropic = toolbox.get_schema(ToolSchemaFormat.ANTHROPIC)[0]

    assert native.parameters["properties"]["query"]["description"] == "Search query"
    assert openai["type"] == "function"
    assert openai["function"]["name"] == "search"
    assert anthropic["input_schema"] == native.parameters
    assert toolbox.get("search").to_openai_schema() == openai
    assert toolbox.get("search").parse_arguments('{"query": "docs"}') == {
        "query": "docs",
        "limit": 10,
    }


def test_annotated_description_is_included_in_callable_schema() -> None:
    toolbox = Toolbox()

    @toolbox.tool("Greet")
    def greet(name: Annotated[str, "Person to greet"]) -> None:
        pass

    parameters = toolbox.get_schema()[0].parameters
    assert parameters["properties"]["name"]["description"] == "Person to greet"


def test_context_controls_availability_and_description() -> None:
    toolbox = Toolbox()

    @toolbox.tool(
        description_from_context(
            SearchClient,
            render=lambda client: f"Search with prefix {client.prefix}",
            fallback="Search",
        ),
        available_when=provided(SearchClient),
    )
    def search(query: str) -> None:
        pass

    tool = toolbox.get("search")
    assert tool is not None
    assert tool.resolve_description() == "Search"
    assert toolbox.get_schema() == []

    schemas = toolbox.get_schema(context=ToolContext(SearchClient("kb:")))
    assert schemas[0].description == "Search with prefix kb:"


@pytest.mark.asyncio
async def test_tool_errors_are_logged_and_returned_by_the_boundary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    toolbox = Toolbox(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    @toolbox.tool("Fail internally")
    def internal_failure() -> None:
        raise RuntimeError("secret")

    with caplog.at_level(logging.ERROR, logger="agenttoolkit.tools.middleware"):
        result = await toolbox.execute("internal_failure")

    assert "Tool 'internal_failure' failed" in caplog.text
    assert result == "Tool failed: secret"


@pytest.mark.asyncio
async def test_tools_do_not_install_an_error_boundary_by_default() -> None:
    toolbox = Toolbox()

    @toolbox.tool("Fail internally")
    def internal_failure() -> None:
        raise RuntimeError("secret")

    with pytest.raises(RuntimeError, match="secret"):
        await toolbox.execute("internal_failure")


def test_duplicate_registration_is_rejected() -> None:
    toolbox = Toolbox()

    @toolbox.tool("First")
    def duplicate() -> None:
        pass

    with pytest.raises(ValueError, match="already registered"):

        @toolbox.tool("Second")
        def duplicate() -> None:
            pass
