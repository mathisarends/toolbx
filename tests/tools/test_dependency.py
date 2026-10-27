import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest

from toolbox import Inject, Toolbox, provide
from toolbox.dependency import DependencyContainer, DependencyProvider


class Settings:
    pass


class Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings


class Connection:
    pass


class First:
    pass


class Second:
    pass


@pytest.mark.asyncio
async def test_dependencies_are_singletons_for_the_container_lifetime() -> None:
    connection_calls = 0

    class Dependencies(DependencyProvider):
        @provide
        def settings(self) -> Settings:
            return Settings()

        @provide
        def client(self, settings: Settings) -> Client:
            return Client(settings)

        @provide
        async def connection(self) -> Connection:
            nonlocal connection_calls
            connection_calls += 1
            return Connection()

    toolbox = Toolbox(dependencies=[Dependencies()])

    @toolbox.tool("Use dependencies")
    async def use(
        value: int,
        client: Inject[Client],
        first: Inject[Connection],
        second: Inject[Connection],
    ) -> tuple[object, ...]:
        return value, client, first, first is second

    assert set(toolbox.schemas()[0].parameters["properties"]) == {"value"}
    first = await toolbox.execute("use", {"value": 3})
    second = await toolbox.execute("use", {"value": 4})

    assert first[0] == 3
    assert first[1] is second[1]
    assert first[2] is second[2]
    assert first[3] is True
    assert connection_calls == 1


@pytest.mark.asyncio
async def test_plain_singletons_can_resolve_without_a_context_manager() -> None:
    class Dependencies(DependencyProvider):
        @provide
        def settings(self) -> Settings:
            return Settings()

    toolbox = Toolbox(dependencies=[Dependencies()])

    @toolbox.tool("Use settings")
    def use(settings: Inject[Settings]) -> Settings:
        return settings

    assert await toolbox.execute("use") is await toolbox.execute("use")


def test_tools_reject_container_and_dependencies_together() -> None:
    container = DependencyContainer()

    with pytest.raises(ValueError, match="either container or dependencies"):
        Toolbox(container=container, dependencies=[])


def test_graph_is_validated_at_construction() -> None:
    class Missing:
        pass

    class Invalid(DependencyProvider):
        @provide
        def settings(self, missing: Missing) -> Settings:
            return Settings()

    with pytest.raises(ValueError, match="Missing dependency provider"):
        DependencyContainer(Invalid())


def test_duplicate_dependency_is_rejected() -> None:
    class Duplicates(DependencyProvider):
        @provide
        def first(self) -> Settings:
            return Settings()

        @provide
        def second(self) -> Settings:
            return Settings()

    with pytest.raises(ValueError, match="Duplicate dependency provider"):
        DependencyContainer(Duplicates())


def test_dependency_cycle_is_rejected() -> None:
    class Cyclic(DependencyProvider):
        @provide
        def first(self, second: Second) -> First:
            return First()

        @provide
        def second(self, first: First) -> Second:
            return Second()

    with pytest.raises(ValueError, match="Cyclic dependency"):
        DependencyContainer(Cyclic())


def test_generator_providers_are_rejected() -> None:
    class Dependencies(DependencyProvider):
        @provide
        def value(self) -> Iterator[Settings]:
            yield Settings()

    with pytest.raises(TypeError, match="application must own resource lifecycles"):
        DependencyContainer(Dependencies())


def test_async_generator_providers_are_rejected() -> None:
    class Dependencies(DependencyProvider):
        @provide
        async def value(self) -> AsyncIterator[Settings]:
            yield Settings()

    with pytest.raises(TypeError, match="application must own resource lifecycles"):
        DependencyContainer(Dependencies())


@pytest.mark.asyncio
async def test_concurrent_resolution_constructs_one_instance() -> None:
    calls = 0

    class Dependencies(DependencyProvider):
        @provide
        async def settings(self) -> Settings:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return Settings()

    container = DependencyContainer(Dependencies())
    first, second = await asyncio.gather(
        container.get(Settings),
        container.get(Settings),
    )

    assert first is second
    assert calls == 1


@pytest.mark.asyncio
async def test_composition_root_can_supply_an_existing_resource() -> None:
    connection = Connection()

    class Dependencies(DependencyProvider):
        def __init__(self, resource: Connection) -> None:
            self.resource = resource

        @provide
        def connection(self) -> Connection:
            return self.resource

    container = DependencyContainer(Dependencies(connection))

    assert await container.get(Connection) is connection
