import logging

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from toolbx import ErrorBoundaryMiddleware, Toolbox, Toolset, tool


def test_exported_schemas_can_be_transformed_without_changing_the_tool() -> None:
    class Search(Toolset, namespace=None):
        @tool("Search")
        def search(self, query: str) -> str:
            return query

    toolbox = Toolbox(Search())
    native = toolbox.schemas()[0]
    openai = toolbox.to_openai()[0]
    anthropic = toolbox.to_anthropic()[0]

    native.parameters["properties"]["query"]["description"] = "Changed native"
    openai["function"]["parameters"]["properties"].clear()
    anthropic["input_schema"]["properties"]["query"]["type"] = "integer"

    fresh = toolbox.schemas()[0].parameters
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


def test_unannotated_signature_parameter_is_rejected_with_its_name() -> None:
    with pytest.raises(TypeError, match="parameter 'value' requires a type annotation"):

        class Invalid(Toolset):
            @tool("Invalid")
            def invalid(self, value) -> None:
                pass


@pytest.mark.asyncio
async def test_model_parameters_stay_nested_unless_params_is_explicit() -> None:
    class User(BaseModel):
        name: str

    class Users(Toolset, namespace=None):
        @tool("Create")
        def create(self, user: User) -> str:
            return user.name

        @tool("Create with options")
        def create_with_options(self, user: User, active: bool = True) -> str:
            return user.name

        @tool("Create with explicit flat input", params=User)
        def create_flat(self, user: User) -> str:
            return user.name

    toolbox = Toolbox(Users())
    nested, extended, flat = toolbox.schemas()
    assert set(nested.parameters["properties"]) == {"user"}
    assert set(extended.parameters["properties"]) == {"user", "active"}
    assert set(flat.parameters["properties"]) == {"name"}
    assert await toolbox.execute("create", {"user": {"name": "Ada"}}) == "Ada"
    assert await toolbox.execute("create_flat", {"name": "Ada"}) == "Ada"


@pytest.mark.asyncio
async def test_call_logging_keeps_arguments_out_of_info_logs(caplog) -> None:
    from toolbx import CallLoggingMiddleware

    class Sensitive(Toolset, namespace=None):
        @tool("Accept a token")
        def accept(self, token: str) -> None:
            pass

    toolbox = Toolbox(Sensitive(), middleware=[CallLoggingMiddleware()])
    with caplog.at_level(logging.INFO, logger="toolbx.tools.middleware"):
        await toolbox.execute("accept", {"token": "sensitive-value"})
    assert "accept called" in caplog.text
    assert "sensitive-value" not in caplog.text

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="toolbx.tools.middleware"):
        await toolbox.execute("accept", {"token": "sensitive-value"})
    assert "sensitive-value" in caplog.text


@pytest.mark.asyncio
async def test_unknown_arguments_are_rejected_in_both_definition_styles() -> None:
    class Params(BaseModel):
        model_config = ConfigDict(extra="ignore")
        value: int

    class Inputs(Toolset, namespace=None):
        @tool("Signature")
        def signature(self, value: int) -> int:
            return value

        @tool("Explicit params", params=Params)
        def explicit(self, params: Params) -> int:
            assert isinstance(params, Params)
            return params.value

    toolbox = Toolbox(Inputs())
    for name in ("signature", "explicit"):
        assert await toolbox.execute(name, {"value": "7"}) == 7
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            await toolbox.execute(name, {"value": 7, "hallucinated": True})
        assert toolbox.get(name).parameters["additionalProperties"] is False
    assert Params.model_config["extra"] == "ignore"


@pytest.mark.asyncio
async def test_execution_uses_the_parameter_binding_resolved_at_registration(
    monkeypatch,
) -> None:
    class Params(BaseModel):
        value: int

    class Inputs(Toolset, namespace=None):
        @tool("Read", params=Params)
        def read(self, params: Params) -> int:
            return params.value

    toolbox = Toolbox(Inputs())
    monkeypatch.setattr(Inputs.read, "__annotations__", {"params": "UndefinedType"})
    assert await toolbox.execute("read", {"value": "7"}) == 7
