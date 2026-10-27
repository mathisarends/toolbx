import pytest

from toolbx import Tool, Toolbox, ToolRequest, Toolset, tool


@pytest.mark.asyncio
async def test_constructor_state_controls_availability_on_each_export_and_call() -> (
    None
):
    class AdminTools(Toolset, namespace=None):
        def __init__(self) -> None:
            self.enabled = False

        @tool("Reset", available_when=lambda self: self.enabled)
        def reset(self) -> str:
            return "reset"

    tools = AdminTools()
    toolbox = Toolbox(toolsets=(tools,))
    assert toolbox.schemas() == toolbox.to_openai() == toolbox.to_anthropic() == []
    with pytest.raises(LookupError, match="Unknown tool"):
        await toolbox.execute(ToolRequest("reset"))
    tools.enabled = True
    assert [schema.name for schema in toolbox.schemas()] == ["reset"]
    assert await toolbox.execute(ToolRequest("reset")) == "reset"
    tools.enabled = False
    assert toolbox.schemas() == []


def test_only_toolset_instances_can_be_registered() -> None:
    class Plain:
        @tool("Ping")
        def ping(self) -> None:
            pass

    class Empty(Toolset):
        pass

    with pytest.raises(TypeError, match="Toolset instance"):
        Toolbox().add(Plain(), namespace="plain")
    with pytest.raises(TypeError, match="expects an instance"):
        Toolbox(toolsets=(Empty,))
    with pytest.raises(ValueError, match="does not define any tools"):
        Toolbox(toolsets=(Empty(),))


@pytest.mark.parametrize("kind", [staticmethod, classmethod])
@pytest.mark.parametrize("outside", [False, True])
def test_marked_descriptors_fail_at_class_definition(kind, outside: bool) -> None:
    def method(self) -> None:
        pass

    descriptor = (
        tool("Invalid")(kind(method)) if outside else kind(tool("Invalid")(method))
    )
    with pytest.raises(TypeError, match="must be an instance method"):
        type("Invalid", (Toolset,), {"invalid": descriptor})


def test_unmarked_overrides_and_helpers_are_not_exposed() -> None:
    class Base(Toolset):
        @tool("First")
        def first(self) -> None:
            pass

        @tool("Second")
        def second(self) -> None:
            pass

    class Derived(Base):
        def first(self) -> None:
            pass

        @staticmethod
        def helper() -> None:
            pass

        @classmethod
        def other_helper(cls) -> None:
            pass

    assert [schema.name for schema in Toolbox(toolsets=(Derived(),)).schemas()] == [
        "derived_second"
    ]


def test_decorator_metadata_is_copied_and_registered_with_the_bound_method() -> None:
    tags = ["read"]
    metadata = {"owner": "platform"}

    class MetadataTools(Toolset):
        @tool("Read", tags=tags, metadata=metadata, requires_approval=True)
        def read(self) -> None:
            pass

    tools = MetadataTools()
    tags.append("write")
    metadata["owner"] = "changed"
    registered = Toolbox(toolsets=(tools,)).get("metadata_read")
    assert registered.fn.__self__ is tools
    assert registered.namespace == "metadata"
    assert registered.local_name == "read"
    assert registered.tags == frozenset({"read"})
    assert registered.metadata == {"owner": "platform"}
    assert registered.requires_approval
    with pytest.raises(TypeError):
        registered.metadata["owner"] = "changed"


def test_callable_objects_cannot_replace_decorated_methods() -> None:
    class CallableObject:
        def __call__(self) -> None:
            pass

    with pytest.raises(TypeError, match="must be an instance method"):

        class Invalid(Toolset):
            invalid = tool("Invalid")(CallableObject())


def test_docstring_is_the_description_fallback() -> None:
    class DocTools(Toolset, namespace=None):
        @tool()
        def lookup(self) -> None:
            """Look up a record.

            Returns nothing yet.
            """

        @tool("Explicit wins")
        def other(self) -> None:
            """Ignored docstring."""

    toolbox = Toolbox(toolsets=(DocTools(),))
    assert toolbox.get("lookup").description == (
        "Look up a record.\n\nReturns nothing yet."
    )
    assert toolbox.get("other").description == "Explicit wins"


def test_tools_without_description_or_docstring_are_rejected() -> None:
    with pytest.raises(ValueError, match="'silent' needs a description"):

        class Silent(Toolset):
            @tool()
            def silent(self) -> None:
                pass

    with pytest.raises(ValueError, match="'direct' needs a description"):
        Tool("direct", "", lambda: None)


def test_tool_name_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        tool("Description", "name")  # type: ignore[misc]
