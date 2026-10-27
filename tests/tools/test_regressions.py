import pytest
from pydantic import BaseModel

from toolbox import ErrorBoundaryMiddleware, Toolbox, ToolSchemaFormat, Toolset, tool


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


@pytest.mark.parametrize("name", ["a" * 65, "not a name!"])
def test_invalid_local_names_are_rejected_before_registration(name: str) -> None:
    with pytest.raises(ValueError):

        class Invalid(Toolset):
            @tool("Invalid", name=name)
            def action(self) -> None:
                pass


def test_name_limit_applies_to_the_complete_exported_name() -> None:
    class Names(Toolset, namespace=None):
        @tool("One-character local name", name="x")
        def action(self) -> None:
            pass

    toolbox = Toolbox()
    toolbox.add(Names(), namespace="n" * 62)
    assert len(next(iter(toolbox)).name) == 64

    before = list(toolbox)
    with pytest.raises(ValueError, match="at most 64 characters"):
        toolbox.add(Names(), namespace="n" * 63)
    assert list(toolbox) == before


@pytest.mark.asyncio
async def test_bound_methods_keep_regular_parameters_named_cls_and_self() -> None:
    class Names(Toolset, namespace=None):
        @tool("Classify")
        def classify(self, cls: str, text: str) -> str:
            return f"{cls}:{text}"

        @tool("Echo")
        def echo(instance, self: str) -> str:
            return self

    toolbox = Toolbox(Names())
    assert await toolbox.execute("classify", {"cls": "news", "text": "hello"}) == (
        "news:hello"
    )
    assert await toolbox.execute("echo", {"self": "hello"}) == "hello"


@pytest.mark.asyncio
async def test_params_model_and_nested_models_reach_the_method_as_models() -> None:
    class Item(BaseModel):
        value: int

    class Params(BaseModel):
        item: Item

    class Models(Toolset, namespace=None):
        @tool("Read nested model", params=Params)
        def read(self, params: Params) -> int:
            assert isinstance(params, Params)
            assert isinstance(params.item, Item)
            return params.item.value

    assert await Toolbox(Models()).execute("read", {"item": {"value": "7"}}) == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [TimeoutError, RuntimeError])
async def test_optional_error_boundary_names_exceptions_without_text(
    exception: type[Exception],
) -> None:
    class Failure(Toolset, namespace=None):
        @tool("Fail")
        def fail(self) -> None:
            raise exception()

    toolbox = Toolbox(Failure(), middleware=[ErrorBoundaryMiddleware()])
    assert await toolbox.execute("fail") == f"Tool failed: {exception.__name__}"


@pytest.mark.parametrize("explicit_params", [False, True])
def test_variadic_toolset_methods_fail_at_class_definition(
    explicit_params: bool,
) -> None:
    class Params(BaseModel):
        value: str

    with pytest.raises(TypeError, match="cannot use variadic parameters"):

        class Invalid(Toolset):
            @tool("Invalid", params=Params if explicit_params else None)
            def invalid(self, *values: str) -> None:
                pass
