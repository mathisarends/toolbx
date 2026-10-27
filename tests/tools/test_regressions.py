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
