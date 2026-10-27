import logging
from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from toolbox import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    Toolbox,
    Toolset,
)
from toolbox import tool as mark_tool


class SearchParams(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, ge=1)


class SearchClient:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix


@pytest.mark.asyncio
async def test_plain_signature_is_validated_and_sync_result_is_returned() -> None:
    toolbox = Toolbox(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    class DefinedTools1(Toolset, namespace=None):
        @mark_tool("Add numbers")
        def add(self, a: int, b: int = 1) -> int:
            return a + b

    toolbox.add(DefinedTools1())
    assert await toolbox.execute("add", {"a": "2"}) == 3
    invalid = await toolbox.execute("add", {})
    assert isinstance(invalid, str)
    assert invalid.startswith("Tool failed: ")
    assert "a" in invalid


def test_schema_is_provider_neutral_with_adapters() -> None:
    toolbox = Toolbox()

    class DefinedTools2(Toolset, namespace=None):
        @mark_tool("Search")
        def search(self, params: SearchParams) -> None:
            pass

    toolbox.add(DefinedTools2())
    native = toolbox.schemas()[0]
    openai = toolbox.to_openai()[0]
    anthropic = toolbox.to_anthropic()[0]
    assert native.parameters["properties"]["query"]["description"] == "Search query"
    assert openai["type"] == "function"
    assert openai["function"]["name"] == "search"
    assert anthropic["input_schema"] == native.parameters
    assert toolbox.get("search").to_openai_schema() == openai


def test_annotated_description_is_included_in_callable_schema() -> None:
    toolbox = Toolbox()

    class DefinedTools3(Toolset, namespace=None):
        @mark_tool("Greet")
        def greet(self, name: Annotated[str, "Person to greet"]) -> None:
            pass

    toolbox.add(DefinedTools3())
    parameters = toolbox.schemas()[0].parameters
    assert parameters["properties"]["name"]["description"] == "Person to greet"


@pytest.mark.asyncio
async def test_tool_errors_are_logged_and_returned_by_the_boundary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    toolbox = Toolbox(middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()))

    class DefinedTools4(Toolset, namespace=None):
        @mark_tool("Fail internally")
        def internal_failure(self) -> None:
            raise RuntimeError("secret")

    toolbox.add(DefinedTools4())
    with caplog.at_level(logging.ERROR, logger="toolbox.tools.middleware"):
        result = await toolbox.execute("internal_failure")
    assert "Tool 'internal_failure' failed" in caplog.text
    assert result == "Tool failed: secret"


@pytest.mark.asyncio
async def test_tools_do_not_install_an_error_boundary_by_default() -> None:
    toolbox = Toolbox()

    class DefinedTools5(Toolset, namespace=None):
        @mark_tool("Fail internally")
        def internal_failure(self) -> None:
            raise RuntimeError("secret")

    toolbox.add(DefinedTools5())
    with pytest.raises(RuntimeError, match="secret"):
        await toolbox.execute("internal_failure")


def test_duplicate_registration_is_rejected() -> None:
    toolbox = Toolbox()

    class DefinedTools6(Toolset, namespace=None):
        @mark_tool("First")
        def duplicate(self) -> None:
            pass

    toolbox.add(DefinedTools6())
    with pytest.raises(ValueError, match="already registered"):

        class DefinedTools7(Toolset, namespace=None):
            @mark_tool("Second")
            def duplicate(self) -> None:
                pass

        toolbox.add(DefinedTools7())
