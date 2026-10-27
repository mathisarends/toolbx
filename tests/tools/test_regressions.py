import pytest

from toolbox import Toolbox, ToolSchemaFormat, Toolset, tool


def test_exported_schemas_can_be_transformed_without_changing_the_tool() -> None:
    class Search(Toolset, namespace=None):
        @tool("Search")
        def search(self, query: str) -> str:
            return query

    toolbox = Toolbox(Search())
    native = toolbox.get_schema()[0]
    openai = toolbox.get_schema(ToolSchemaFormat.OPENAI)[0]
    anthropic = toolbox.get_schema(ToolSchemaFormat.ANTHROPIC)[0]

    native.parameters["properties"]["query"]["description"] = "Changed native"
    openai["function"]["parameters"]["properties"].clear()
    anthropic["input_schema"]["properties"]["query"]["type"] = "integer"

    fresh = toolbox.get_schema()[0].parameters
    assert fresh["properties"]["query"]["type"] == "string"
    assert "description" not in fresh["properties"]["query"]


def test_merge_leaves_the_destination_unchanged_on_a_late_collision() -> None:
    class Existing(Toolset, namespace=None):
        @tool("Existing")
        def shared(self) -> str:
            return "existing"

    class Incoming(Toolset, namespace=None):
        @tool("Before collision")
        def first(self) -> None:
            pass

        @tool("Collision")
        def shared(self) -> str:
            return "incoming"

        @tool("After collision")
        def last(self) -> None:
            pass

    destination = Toolbox(Existing())
    incoming = Toolbox(Incoming())
    original = list(destination)
    with pytest.raises(ValueError, match=r"shared.*already registered"):
        destination.merge(incoming)
    assert list(destination) == original

    destination.merge(incoming, replace=True)
    assert [item.name for item in destination] == ["shared", "first", "last"]
    assert destination.get("shared").description == "Collision"
