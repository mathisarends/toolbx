from typing import Any

import pytest
from pydantic import BaseModel

from toolbox import (
    Inject,
    Toolbox,
    tool,
)


class SearchParams(BaseModel):
    query: str
    limit: int = 10


class SearchClient:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix


class SearchPlugin:
    def __init__(self, source: str) -> None:
        self.source = source

    @tool(
        "Search a configured source",
        tags=["search"],
        metadata={"owner": "knowledge"},
    )
    async def search(
        self,
        params: SearchParams,
    ) -> str:
        return f"{self.source}:{params.query}:{params.limit}"

    @tool("Fetch one result", name="fetch", requires_approval=True)
    def get_result(self, result_id: str) -> str:
        return f"{self.source}:{result_id}"

    def helper(self) -> None:
        raise AssertionError("Helpers must not be exposed")


@pytest.mark.asyncio
async def test_plugin_registers_bound_methods_with_names_and_metadata() -> None:
    plugin = SearchPlugin("docs")
    toolbox = Toolbox()

    registered = toolbox.add_plugin(plugin, name="knowledge")

    assert [item.name for item in registered] == [
        "knowledge_search",
        "knowledge_fetch",
    ]
    assert [schema.name for schema in toolbox.get_schema()] == [
        "knowledge_search",
        "knowledge_fetch",
    ]
    search = toolbox.get("knowledge_search")
    fetch = toolbox.get("knowledge_fetch")
    assert search is not None
    assert fetch is not None
    assert search.fn.__self__ is plugin
    assert search.plugin_name == "knowledge"
    assert search.local_name == "search"
    assert search.tags == frozenset({"search"})
    assert search.extra == {"owner": "knowledge"}
    assert fetch.requires_approval is True
    assert toolbox.get("helper") is None
    assert await toolbox.execute("knowledge_search", {"query": "DI"}) == ("docs:DI:10")
    fetched = await toolbox.execute("knowledge_fetch", {"result_id": "r-1"})
    assert fetched == "docs:r-1"


def test_plugin_methods_reject_inject_parameters() -> None:
    class InvalidPlugin:
        @tool("Invalid")
        def invalid(self, client: Inject[SearchClient]) -> None:
            pass

    with pytest.raises(TypeError, match="declare runtime dependencies"):
        Toolbox().add_plugin(InvalidPlugin(), name="invalid")


def test_plugin_registration_is_atomic_on_existing_name_collision() -> None:
    toolbox = Toolbox()

    @toolbox.tool("Existing")
    def knowledge_fetch(result_id: str) -> str:
        return result_id

    with pytest.raises(ValueError, match="already registered"):
        toolbox.add_plugin(SearchPlugin("docs"), name="knowledge")
    assert [item.name for item in toolbox] == ["knowledge_fetch"]


def test_plugin_registration_is_atomic_on_invalid_method() -> None:
    class InvalidPlugin:
        @tool("Valid")
        def valid(self, value: str) -> str:
            return value

        @tool("Invalid")
        def invalid(self, *values: str) -> None:
            pass

    toolbox = Toolbox()
    with pytest.raises(TypeError, match="cannot use variadic parameters"):
        toolbox.add_plugin(InvalidPlugin(), name="invalid")
    assert len(toolbox) == 0


def test_plugin_rejects_duplicate_local_tool_names() -> None:
    class DuplicatePlugin:
        @tool("First", name="same")
        def first(self) -> None:
            pass

        @tool("Second", name="same")
        def second(self) -> None:
            pass

    with pytest.raises(ValueError, match="duplicate tool 'same'"):
        Toolbox().add_plugin(DuplicatePlugin(), name="duplicate")


@pytest.mark.parametrize("name", ["", "not valid", "invalid.dot"])
def test_plugin_rejects_invalid_plugin_names(name: str) -> None:
    with pytest.raises(ValueError, match="Plugin name must contain"):
        Toolbox().add_plugin(SearchPlugin("docs"), name=name)


@pytest.mark.parametrize("name", ["", "not valid", "invalid.dot"])
def test_plugin_rejects_invalid_local_tool_names(name: str) -> None:
    class InvalidNamePlugin:
        @tool("Invalid name", name=name)
        def method(self) -> None:
            pass

    with pytest.raises(ValueError, match="Plugin tool name must contain"):
        Toolbox().add_plugin(InvalidNamePlugin(), name="plugin")


def test_plugin_requires_at_least_one_tool() -> None:
    class EmptyPlugin:
        pass

    with pytest.raises(ValueError, match="does not define any tools"):
        Toolbox().add_plugin(EmptyPlugin(), name="empty")
    with pytest.raises(TypeError, match="expects an instance"):
        Toolbox().add_plugin(EmptyPlugin, name="empty")


def test_plugin_name_can_only_be_registered_once() -> None:
    class OtherPlugin:
        @tool("Other")
        def other(self) -> None:
            pass

    toolbox = Toolbox()
    toolbox.add_plugin(SearchPlugin("docs"), name="knowledge")
    with pytest.raises(ValueError, match="Plugin 'knowledge' is already registered"):
        toolbox.add_plugin(OtherPlugin(), name="knowledge")


@pytest.mark.parametrize(
    ("kind", "decorator_outside"),
    [("static", False), ("static", True), ("class", False), ("class", True)],
)
def test_plugin_tools_must_be_instance_methods(
    kind: str, decorator_outside: bool
) -> None:
    if kind == "static" and not decorator_outside:

        class InvalidPlugin:
            @staticmethod
            @tool("Invalid")
            def invalid() -> None:
                pass

    elif kind == "static":

        class InvalidPlugin:
            @tool("Invalid")
            @staticmethod
            def invalid() -> None:
                pass

    elif not decorator_outside:

        class InvalidPlugin:
            @classmethod
            @tool("Invalid")
            def invalid(cls) -> None:
                pass

    else:

        class InvalidPlugin:
            @tool("Invalid")
            @classmethod
            def invalid(cls) -> None:
                pass

    with pytest.raises(TypeError, match="must be an instance method"):
        Toolbox().add_plugin(InvalidPlugin(), name="invalid")


def test_plugin_ignores_unmarked_static_and_class_methods() -> None:
    class Plugin:
        @staticmethod
        def static_helper() -> None:
            pass

        @classmethod
        def class_helper(cls) -> None:
            pass

        @tool("Visible")
        def visible(self) -> None:
            pass

    registered = Toolbox().add_plugin(Plugin(), name="helpers")
    assert [item.name for item in registered] == ["helpers_visible"]


def test_plugin_rejects_decorated_callable_descriptors() -> None:
    class CallableDescriptor:
        def __call__(self) -> None:
            pass

    class InvalidPlugin:
        invalid = tool("Invalid")(CallableDescriptor())

    with pytest.raises(TypeError, match="must be an instance method"):
        Toolbox().add_plugin(InvalidPlugin(), name="invalid")


def test_plugin_inheritance_respects_undecorated_overrides() -> None:
    class BasePlugin:
        @tool("First")
        def first(self) -> None:
            pass

        @tool("Second")
        def second(self) -> None:
            pass

    class DerivedPlugin(BasePlugin):
        def first(self) -> None:
            pass

        @tool("Third")
        def third(self) -> None:
            pass

    toolbox = Toolbox()
    toolbox.add_plugin(DerivedPlugin(), name="derived")
    assert [item.name for item in toolbox] == ["derived_second", "derived_third"]


def test_plugin_decorator_defensively_copies_metadata() -> None:
    tags = ["read"]
    metadata: dict[str, Any] = {"owner": "platform"}

    class MetadataPlugin:
        @tool("Read", tags=tags, metadata=metadata)
        def read(self) -> None:
            pass

    tags.append("write")
    metadata["owner"] = "changed"
    toolbox = Toolbox()
    toolbox.add_plugin(MetadataPlugin(), name="metadata")
    registered = toolbox.get("metadata_read")
    assert registered is not None
    assert registered.tags == frozenset({"read"})
    assert registered.extra == {"owner": "platform"}
