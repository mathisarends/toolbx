import pytest

from agenttoolkit import AgentToolset, Toolbox, tool


class CatalogService:
    def __init__(self, name: str) -> None:
        self.name = name


class CatalogTools(AgentToolset):
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    @tool("Search the catalog")
    async def search(self, query: str) -> str:
        return f"{self._catalog.name}:{query}"

    @tool("Get one entry", name="get")
    def get_entry(self, entry_id: str) -> str:
        return f"{self._catalog.name}#{entry_id}"


@pytest.mark.asyncio
async def test_toolset_uses_default_namespace_and_constructor_dependencies() -> None:
    toolbox = Toolbox()

    toolbox.add(CatalogTools(CatalogService("docs")))

    assert [schema.name for schema in toolbox.get_schema()] == [
        "catalog_search",
        "catalog_get",
    ]
    assert await toolbox.execute("catalog_search", {"query": "di"}) == "docs:di"
    assert await toolbox.execute("catalog_get", {"entry_id": "1"}) == "docs#1"


@pytest.mark.parametrize(
    ("class_name", "expected"),
    [
        ("CatalogTools", "catalog"),
        ("CatalogToolset", "catalog"),
        ("CatalogToolbox", "catalog"),
        ("CatalogPlugin", "catalog"),
        ("Catalog", "catalog"),
        ("FileSystemTools", "file_system"),
        ("HTTPClientTools", "http_client"),
        ("Tools", "tools"),
    ],
)
def test_default_namespace_is_snake_case_without_suffix(
    class_name: str, expected: str
) -> None:
    toolset = type(class_name, (AgentToolset,), {})

    assert toolset.namespace == expected


def test_namespace_class_argument_overrides_default() -> None:
    class Anything(AgentToolset, namespace="custom"):
        pass

    class Unprefixed(AgentToolset, namespace=None):
        pass

    assert Anything.namespace == "custom"
    assert Unprefixed.namespace is None


def test_toolset_without_namespace_exposes_local_names() -> None:
    class Unprefixed(AgentToolset, namespace=None):
        @tool("Ping")
        def ping(self) -> str:
            return "pong"

    toolbox = Toolbox()
    toolbox.add(Unprefixed())

    assert [item.name for item in toolbox] == ["ping"]


def test_namespace_can_be_overridden_per_instance() -> None:
    toolbox = Toolbox()

    toolbox.add(CatalogTools(CatalogService("docs")))
    toolbox.add(CatalogTools(CatalogService("archive")), namespace="archive")

    assert [item.name for item in toolbox] == [
        "catalog_search",
        "catalog_get",
        "archive_search",
        "archive_get",
    ]


def test_second_instance_without_namespace_is_rejected_with_hint() -> None:
    toolbox = Toolbox()
    toolbox.add(CatalogTools(CatalogService("docs")))

    with pytest.raises(ValueError, match="pass namespace= to register another"):
        toolbox.add(CatalogTools(CatalogService("archive")))
    assert len(toolbox) == 2


def test_invalid_namespace_is_rejected_at_class_definition() -> None:
    with pytest.raises(ValueError, match="Namespace must contain"):

        class Invalid(AgentToolset, namespace="not valid"):
            pass


def test_duplicate_tool_names_are_rejected_at_class_definition() -> None:
    with pytest.raises(ValueError, match="duplicate tool 'same'"):

        class Duplicate(AgentToolset):
            @tool("First", name="same")
            def first(self) -> None:
                pass

            @tool("Second", name="same")
            def second(self) -> None:
                pass


def test_invalid_tool_methods_are_rejected_at_class_definition() -> None:
    with pytest.raises(TypeError, match="must be an instance method"):

        class Invalid(AgentToolset):
            @classmethod
            @tool("Invalid")
            def invalid(cls) -> None:
                pass


def test_subclass_override_replaces_inherited_tool() -> None:
    class Base(AgentToolset, namespace="base"):
        @tool("Base search")
        def search(self) -> str:
            return "base"

    class Derived(Base, namespace="derived"):
        @tool("Derived search")
        def search(self) -> str:
            return "derived"

    toolbox = Toolbox()
    toolbox.add(Derived())

    assert [item.name for item in toolbox] == ["derived_search"]
    assert toolbox.get("derived_search") is not None


def test_plain_object_requires_explicit_namespace() -> None:
    class Plain:
        @tool("Ping")
        def ping(self) -> str:
            return "pong"

    toolbox = Toolbox()
    with pytest.raises(TypeError, match="pass namespace="):
        toolbox.add(Plain())

    toolbox.add(Plain(), namespace="plain")
    assert [item.name for item in toolbox] == ["plain_ping"]


def test_collisions_name_every_conflict_and_leave_registry_unchanged() -> None:
    toolbox = Toolbox()

    @toolbox.tool("Existing search")
    def catalog_search(query: str) -> str:
        return query

    @toolbox.tool("Existing get")
    def catalog_get(entry_id: str) -> str:
        return entry_id

    with pytest.raises(ValueError) as exc_info:
        toolbox.add(CatalogTools(CatalogService("docs")))

    message = str(exc_info.value)
    assert "Tool 'catalog_search' is already registered" in message
    assert "Tool 'catalog_get' is already registered" in message
    assert "defined by a function tool" in message
    assert [item.name for item in toolbox] == ["catalog_search", "catalog_get"]


def test_collision_between_toolsets_names_the_existing_toolset() -> None:
    class First(AgentToolset, namespace=None):
        @tool("Ping")
        def ping(self) -> None:
            pass

    class Second(AgentToolset, namespace=None):
        @tool("Ping")
        def ping(self) -> None:
            pass

    toolbox = Toolbox()
    toolbox.add(First())

    with pytest.raises(ValueError, match=r"'ping' is already registered.*First"):
        toolbox.add(Second())


def test_constructor_registers_toolsets_in_order() -> None:
    class Files(AgentToolset):
        @tool("Read")
        def read(self) -> None:
            pass

    toolbox = Toolbox(CatalogTools(CatalogService("docs")), Files())

    assert [item.name for item in toolbox] == [
        "catalog_search",
        "catalog_get",
        "files_read",
    ]


def test_constructor_rejects_colliding_toolsets() -> None:
    with pytest.raises(ValueError, match="pass namespace="):
        Toolbox(CatalogTools(CatalogService("a")), CatalogTools(CatalogService("b")))


def test_include_selects_tools_by_local_name() -> None:
    toolbox = Toolbox()

    toolbox.add(CatalogTools(CatalogService("docs")), include={"get"})

    assert [item.name for item in toolbox] == ["catalog_get"]


def test_exclude_removes_tools_by_local_name() -> None:
    toolbox = Toolbox()

    toolbox.add(CatalogTools(CatalogService("docs")), exclude=["get"])

    assert [item.name for item in toolbox] == ["catalog_search"]


def test_include_and_exclude_combine() -> None:
    toolbox = Toolbox()

    toolbox.add(
        CatalogTools(CatalogService("docs")),
        include={"search", "get"},
        exclude={"search"},
    )

    assert [item.name for item in toolbox] == ["catalog_get"]


def test_filters_reject_unknown_tool_names() -> None:
    toolbox = Toolbox()

    with pytest.raises(ValueError, match="no tools named delete, purge"):
        toolbox.add(CatalogTools(CatalogService("docs")), exclude={"purge", "delete"})
    assert len(toolbox) == 0


def test_filters_reject_selecting_nothing() -> None:
    with pytest.raises(ValueError, match="selects no tools"):
        Toolbox().add(CatalogTools(CatalogService("docs")), exclude={"search", "get"})


def test_filters_reject_a_bare_string() -> None:
    with pytest.raises(TypeError, match="collections of tool names"):
        Toolbox().add(CatalogTools(CatalogService("docs")), include="search")
