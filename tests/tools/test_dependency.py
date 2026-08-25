import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest

from agenttoolkit import Inject, Tools, provide
from agenttoolkit.dependency import DependencyContainer, DependencyProvider


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
    events: list[str] = []

    class Dependencies(DependencyProvider):
        @provide
        def settings(self) -> Settings:
            return Settings()

        @provide
        def client(self, settings: Settings) -> Client:
            return Client(settings)

        @provide
        async def connection(self) -> AsyncIterator[Connection]:
            events.append("open")
            try:
                yield Connection()
            finally:
                events.append("close")

    tools = Tools(dependencies=[Dependencies()])

    @tools.tool("Use dependencies")
    async def use(
        value: int,
        client: Inject[Client],
        first: Inject[Connection],
        second: Inject[Connection],
    ) -> tuple[object, ...]:
        return value, client, first, first is second

    assert set(tools.get_schema()[0].parameters["properties"]) == {"value"}
    async with tools:
        first = await tools.execute("use", {"value": 3})
        second = await tools.execute("use", {"value": 4})

    assert first[0] == 3
    assert first[1] is second[1]
    assert first[2] is second[2]
    assert first[3] is True
    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_plain_singletons_can_resolve_without_a_context_manager() -> None:
    class Dependencies(DependencyProvider):
        @provide
        def settings(self) -> Settings:
            return Settings()

    tools = Tools(dependencies=[Dependencies()])

    @tools.tool("Use settings")
    def use(settings: Inject[Settings]) -> Settings:
        return settings

    assert await tools.execute("use") is await tools.execute("use")


def test_tools_reject_container_and_dependencies_together() -> None:
    container = DependencyContainer()

    with pytest.raises(ValueError, match="either container or dependencies"):
        Tools(container=container, dependencies=[])


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


@pytest.mark.asyncio
async def test_synchronous_generator_is_closed() -> None:
    events: list[str] = []

    class Dependencies(DependencyProvider):
        @provide
        def value(self) -> Iterator[Settings]:
            try:
                yield Settings()
            finally:
                events.append("closed")

    container = DependencyContainer(Dependencies())
    async with container:
        await container.get(Settings)
    assert events == ["closed"]


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
async def test_container_can_be_reused_after_cleanup() -> None:
    class Dependencies(DependencyProvider):
        @provide
        def settings(self) -> Settings:
            return Settings()

    container = DependencyContainer(Dependencies())
    async with container:
        first = await container.get(Settings)
    async with container:
        second = await container.get(Settings)

    assert first is not second


@pytest.mark.asyncio
async def test_container_rejects_nested_lifetimes() -> None:
    container = DependencyContainer()

    async with container:
        with pytest.raises(RuntimeError, match="already active"):
            await container.__aenter__()


@pytest.mark.asyncio
async def test_aclose_cleans_up_resolved_resources() -> None:
    events: list[str] = []

    class Dependencies(DependencyProvider):
        @provide
        async def connection(self) -> AsyncIterator[Connection]:
            try:
                yield Connection()
            finally:
                events.append("closed")

    container = DependencyContainer(Dependencies())
    await container.get(Connection)
    await container.aclose()

    assert events == ["closed"]
