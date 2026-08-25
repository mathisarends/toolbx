from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import IntEnum
from types import MappingProxyType, TracebackType
from typing import Any, get_args, get_origin, get_type_hints


class Scope(IntEnum):
    """Lifetime of a dependency, from longest to shortest lived."""

    APP = 0
    TURN = 1
    CALL = 2


@dataclass(frozen=True, slots=True)
class _ProvideMetadata:
    scope: Scope


def provide[F: Callable[..., Any]](
    func: F | None = None,
    *,
    scope: Scope = Scope.CALL,
) -> F | Callable[[F], F]:
    """Mark a ``DependencyProvider`` method as a dependency factory."""

    def decorate(factory: F) -> F:
        factory_with_metadata: Any = factory
        factory_with_metadata.__dependency_provider__ = _ProvideMetadata(Scope(scope))
        return factory

    return decorate(func) if func is not None else decorate


class DependencyProvider:
    """Base class for collections of dependency factory methods."""


@dataclass(frozen=True, slots=True)
class _Definition:
    dependency: type
    factory: Callable[..., Any]
    dependencies: Mapping[str, type]
    scope: Scope
    is_generator: bool
    is_async_generator: bool


@dataclass(slots=True)
class _ScopeState:
    scope: Scope
    stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    values: dict[type, Any] = field(default_factory=dict)
    pending: dict[type, Any] = field(default_factory=dict)


class DependencyContainer:
    """Validated dependency graph and owner of dependency lifetimes."""

    def __init__(
        self,
        *providers: DependencyProvider,
    ) -> None:
        self._definitions = MappingProxyType(self._collect(providers))
        self._validate_graph()
        self._app_state: _ScopeState | None = None
        self._turn_state: ContextVar[_ScopeState | None] = ContextVar(
            f"turn_scope_{id(self)}", default=None
        )
        self._call_state: ContextVar[_ScopeState | None] = ContextVar(
            f"call_scope_{id(self)}", default=None
        )

    async def __aenter__(self) -> DependencyContainer:
        if self._app_state is not None:
            raise RuntimeError("The application scope is already active")
        state = _ScopeState(Scope.APP)
        await state.stack.__aenter__()
        self._app_state = state
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        state = self._app_state
        try:
            if state is not None:
                return await state.stack.__aexit__(exc_type, exc_value, traceback)
            return None
        finally:
            self._app_state = None

    @asynccontextmanager
    async def scope(self, scope: Scope) -> AsyncGenerator[DependencyContainer]:
        scope = Scope(scope)
        if scope is Scope.APP:
            raise ValueError("Use 'async with container' to open the APP scope")
        if self._app_state is None:
            raise RuntimeError("The APP scope is not active")

        variable = self._turn_state if scope is Scope.TURN else self._call_state
        if variable.get() is not None:
            raise RuntimeError(f"The {scope.name} scope is already active")
        state = _ScopeState(scope)
        await state.stack.__aenter__()
        token = variable.set(state)
        try:
            yield self
        except BaseException as error:
            suppressed = await state.stack.__aexit__(
                type(error), error, error.__traceback__
            )
            if not suppressed:
                raise
        else:
            await state.stack.__aexit__(None, None, None)
        finally:
            variable.reset(token)

    async def get[T](self, dependency: type[T]) -> T:
        """Resolve one dependency in the currently active scopes."""
        definition = self._definitions.get(dependency)
        if definition is None:
            name = getattr(dependency, "__name__", repr(dependency))
            raise LookupError(f"No dependency provider is registered for '{name}'")
        state = self._state_for(definition.scope)
        if dependency in state.values:
            return state.values[dependency]

        # One task performs construction; concurrent users await the same result.
        pending = state.pending.get(dependency)
        if pending is not None:
            return await pending

        import asyncio

        future = asyncio.get_running_loop().create_future()
        state.pending[dependency] = future
        try:
            value = await self._create(definition, state)
            state.values[dependency] = value
            future.set_result(value)
            return value
        except BaseException as error:
            future.set_exception(error)
            # The creator observes the exception directly; consume the future's
            # exception when nobody else was waiting for it.
            future.exception()
            raise
        finally:
            state.pending.pop(dependency, None)

    def has(self, dependency: type) -> bool:
        return dependency in self._definitions

    def _state_for(self, scope: Scope) -> _ScopeState:
        if self._app_state is None:
            raise RuntimeError("The APP scope is not active")
        if scope is Scope.APP:
            return self._app_state
        state = (
            self._turn_state.get() if scope is Scope.TURN else self._call_state.get()
        )
        if state is None:
            raise RuntimeError(f"The {scope.name} scope is not active")
        return state

    async def _create(self, definition: _Definition, state: _ScopeState) -> Any:
        kwargs = {
            name: await self.get(required)
            for name, required in definition.dependencies.items()
        }
        if definition.is_async_generator:
            manager = asynccontextmanager(definition.factory)(**kwargs)
            return await state.stack.enter_async_context(manager)
        if definition.is_generator:
            manager = _async_context_from_generator(definition.factory, kwargs)
            return await state.stack.enter_async_context(manager)
        value = definition.factory(**kwargs)
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _collect(
        providers: tuple[DependencyProvider, ...],
    ) -> dict[type, _Definition]:
        definitions: dict[type, _Definition] = {}
        for provider in providers:
            if not isinstance(provider, DependencyProvider):
                raise TypeError("Providers must inherit from DependencyProvider")
            for _, factory in inspect.getmembers(provider, predicate=inspect.ismethod):
                metadata = getattr(factory, "__dependency_provider__", None)
                if metadata is None:
                    continue
                hints = get_type_hints(factory, include_extras=True)
                annotation = hints.get("return")
                dependency = _provided_type(annotation, factory)
                if dependency in definitions:
                    name = getattr(dependency, "__name__", repr(dependency))
                    raise ValueError(f"Duplicate dependency provider for '{name}'")
                required: dict[str, type] = {}
                for name in inspect.signature(factory).parameters:
                    if name not in hints:
                        factory_name = getattr(
                            factory, "__name__", type(factory).__name__
                        )
                        raise TypeError(
                            f"Dependency parameter '{name}' in {factory_name} "
                            "must have a type annotation"
                        )
                    required[name] = hints[name]
                definitions[dependency] = _Definition(
                    dependency=dependency,
                    factory=factory,
                    dependencies=MappingProxyType(required),
                    scope=metadata.scope,
                    is_generator=inspect.isgeneratorfunction(factory),
                    is_async_generator=inspect.isasyncgenfunction(factory),
                )
        return definitions

    def _validate_graph(self) -> None:
        for definition in self._definitions.values():
            for required in definition.dependencies.values():
                target = self._definitions.get(required)
                if target is None:
                    name = getattr(required, "__name__", repr(required))
                    raise ValueError(
                        f"Missing dependency provider for '{name}', required by "
                        f"'{definition.dependency.__name__}'"
                    )
                if target.scope > definition.scope:
                    raise ValueError(
                        f"Invalid scope dependency: {definition.scope.name} "
                        f"'{definition.dependency.__name__}' depends on "
                        f"{target.scope.name} '{target.dependency.__name__}'"
                    )

        visiting: set[type] = set()
        visited: set[type] = set()

        def visit(dependency: type) -> None:
            if dependency in visiting:
                raise ValueError(f"Cyclic dependency involving '{dependency.__name__}'")
            if dependency in visited:
                return
            visiting.add(dependency)
            for required in self._definitions[dependency].dependencies.values():
                visit(required)
            visiting.remove(dependency)
            visited.add(dependency)

        for dependency in self._definitions:
            visit(dependency)


def _provided_type(annotation: Any, factory: Callable[..., Any]) -> type:
    factory_name = getattr(factory, "__name__", type(factory).__name__)
    if annotation is None:
        raise TypeError(f"Dependency provider '{factory_name}' needs a return type")
    if inspect.isgeneratorfunction(factory) or inspect.isasyncgenfunction(factory):
        args = get_args(annotation)
        if len(args) != 1 or get_origin(annotation) not in {Iterator, AsyncIterator}:
            raise TypeError(
                f"Generator provider '{factory_name}' must return "
                "Iterator[T] or AsyncIterator[T]"
            )
        return args[0]
    return annotation


@asynccontextmanager
async def _async_context_from_generator(
    factory: Callable[..., Iterator[Any]], kwargs: dict[str, Any]
) -> AsyncGenerator[Any]:
    iterator = factory(**kwargs)
    try:
        yield next(iterator)
    except StopIteration as error:
        raise RuntimeError("Dependency generator did not yield") from error
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            close()
