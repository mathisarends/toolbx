from collections.abc import AsyncIterator, Iterator

import pytest

from agenttoolkit import (
    Inject,
    Scope,
    Tools,
    provide,
)
from agenttoolkit.dependency import DependencyContainer, DependencyProvider


class Settings:
    pass


class Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings


class TurnState:
    pass


class Connection:
    pass


class First:
    pass


class Second:
    pass


@pytest.mark.asyncio
async def test_scopes_injection_and_lifecycle() -> None:
    events: list[str] = []

    class Dependencies(DependencyProvider):
        @provide(scope=Scope.APP)
        def settings(self) -> Settings:
            return Settings()

        @provide(scope=Scope.APP)
        def client(self, settings: Settings) -> Client:
            return Client(settings)

        @provide(scope=Scope.TURN)
        def turn(self) -> TurnState:
            return TurnState()

        @provide
        async def connection(self) -> AsyncIterator[Connection]:
            events.append("open")
            try:
                yield Connection()
            finally:
                events.append("close")

    container = DependencyContainer(Dependencies())
    tools = Tools(container=container)

    @tools.tool("Use dependencies")
    async def use(
        value: int,
        client: Inject[Client],
        turn: Inject[TurnState],
        first: Inject[Connection],
        second: Inject[Connection],
    ) -> tuple[object, ...]:
        return value, client, turn, first is second

    assert set(tools.get_schema()[0].parameters["properties"]) == {"value"}
    async with container:
        async with container.scope(Scope.TURN):
            first = await tools.execute("use", {"value": 3})
            second = await tools.execute("use", {"value": 4})

    assert first[0] == 3
    assert first[1] is second[1]
    assert first[2] is second[2]
    assert first[3] is True
    assert events == ["open", "close", "open", "close"]


@pytest.mark.asyncio
async def test_tools_accept_providers_and_own_lifecycle() -> None:
    events: list[str] = []

    class Dependencies(DependencyProvider):
        @provide(scope=Scope.APP)
        def settings(self) -> Settings:
            return Settings()

        @provide
        async def connection(self) -> AsyncIterator[Connection]:
            events.append("open")
            try:
                yield Connection()
            finally:
                events.append("close")

    tools = Tools(dependencies=[Dependencies()])

    @tools.tool("Use dependencies")
    def use(settings: Inject[Settings], connection: Inject[Connection]) -> bool:
        return settings is not None and connection is not None

    async with tools:
        assert await tools.execute("use") is True

    assert events == ["open", "close"]


@pytest.mark.asyncio
async def test_tools_exposes_turn_scope_without_exposing_container() -> None:
    class Dependencies(DependencyProvider):
        @provide(scope=Scope.TURN)
        def turn_state(self) -> TurnState:
            return TurnState()

    tools = Tools(dependencies=[Dependencies()])

    @tools.tool("Use turn state")
    def use(state: Inject[TurnState]) -> TurnState:
        return state

    async with tools:
        async with tools.scope(Scope.TURN):
            assert isinstance(await tools.execute("use"), TurnState)


def test_tools_reject_container_and_dependencies_together() -> None:
    container = DependencyContainer()

    with pytest.raises(ValueError, match="either container or dependencies"):
        Tools(container=container, dependencies=[])


@pytest.mark.asyncio
async def test_turn_dependency_requires_an_explicit_turn_scope() -> None:
    class Dependencies(DependencyProvider):
        @provide(scope=Scope.TURN)
        def state(self) -> TurnState:
            return TurnState()

    container = DependencyContainer(Dependencies())
    tools = Tools(container=container)

    @tools.tool("Use turn state")
    def use(state: Inject[TurnState]) -> None:
        pass

    async with container:
        with pytest.raises(RuntimeError, match="TURN scope is not active"):
            await tools.execute("use")


def test_graph_is_validated_at_construction() -> None:
    class Missing:
        pass

    class Invalid(DependencyProvider):
        @provide(scope=Scope.APP)
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


def test_long_lived_dependency_cannot_depend_on_short_lived_one() -> None:
    class InvalidScopes(DependencyProvider):
        @provide(scope=Scope.APP)
        def first(self, second: Second) -> First:
            return First()

        @provide(scope=Scope.CALL)
        def second(self) -> Second:
            return Second()

    with pytest.raises(ValueError, match="Invalid scope dependency"):
        DependencyContainer(InvalidScopes())


@pytest.mark.asyncio
async def test_synchronous_generator_is_closed() -> None:
    events: list[str] = []

    class Dependencies(DependencyProvider):
        @provide(scope=Scope.APP)
        def value(self) -> Iterator[Settings]:
            try:
                yield Settings()
            finally:
                events.append("closed")

    container = DependencyContainer(Dependencies())
    async with container:
        await container.get(Settings)
    assert events == ["closed"]
