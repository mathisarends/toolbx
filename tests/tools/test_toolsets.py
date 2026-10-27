import pytest

from agenttoolkit import AgentToolset, Tools, tool


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
    tools = Tools()

    tools.add(CatalogTools(CatalogService("docs")))

    assert [schema.name for schema in tools.get_schema()] == [
        "catalog_search",
        "catalog_get",
    ]
    assert await tools.execute("catalog_search", {"query": "di"}) == "docs:di"
    assert await tools.execute("catalog_get", {"entry_id": "1"}) == "docs#1"


@pytest.mark.parametrize(
    ("class_name", "expected"),
    [
        ("CatalogTools", "catalog"),
        ("CatalogToolset", "catalog"),
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

    tools = Tools()
    tools.add(Unprefixed())

    assert [item.name for item in tools] == ["ping"]


def test_namespace_can_be_overridden_per_instance() -> None:
    tools = Tools()

    tools.add(CatalogTools(CatalogService("docs")))
    tools.add(CatalogTools(CatalogService("archive")), namespace="archive")

    assert [item.name for item in tools] == [
        "catalog_search",
        "catalog_get",
        "archive_search",
        "archive_get",
    ]


def test_second_instance_without_namespace_is_rejected_with_hint() -> None:
    tools = Tools()
    tools.add(CatalogTools(CatalogService("docs")))

    with pytest.raises(ValueError, match="pass namespace= to register another"):
        tools.add(CatalogTools(CatalogService("archive")))
    assert len(tools) == 2


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

    tools = Tools()
    tools.add(Derived())

    assert [item.name for item in tools] == ["derived_search"]
    assert tools.get("derived_search") is not None


def test_plain_object_requires_explicit_namespace() -> None:
    class Plain:
        @tool("Ping")
        def ping(self) -> str:
            return "pong"

    tools = Tools()
    with pytest.raises(TypeError, match="pass namespace="):
        tools.add(Plain())

    tools.add(Plain(), namespace="plain")
    assert [item.name for item in tools] == ["plain_ping"]


def test_collisions_name_every_conflict_and_leave_registry_unchanged() -> None:
    tools = Tools()

    @tools.tool("Existing search")
    def catalog_search(query: str) -> str:
        return query

    @tools.tool("Existing get")
    def catalog_get(entry_id: str) -> str:
        return entry_id

    with pytest.raises(ValueError) as exc_info:
        tools.add(CatalogTools(CatalogService("docs")))

    message = str(exc_info.value)
    assert "Tool 'catalog_search' is already registered" in message
    assert "Tool 'catalog_get' is already registered" in message
    assert "defined by a function tool" in message
    assert [item.name for item in tools] == ["catalog_search", "catalog_get"]


def test_collision_between_toolsets_names_the_existing_toolset() -> None:
    class First(AgentToolset, namespace=None):
        @tool("Ping")
        def ping(self) -> None:
            pass

    class Second(AgentToolset, namespace=None):
        @tool("Ping")
        def ping(self) -> None:
            pass

    tools = Tools()
    tools.add(First())

    with pytest.raises(ValueError, match=r"'ping' is already registered.*First"):
        tools.add(Second())
