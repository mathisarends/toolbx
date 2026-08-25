from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from types import MappingProxyType, TracebackType
from typing import Any, Self, get_args, get_origin, get_type_hints

_PROVIDE_MARKER = object()


def provide[F: Callable[..., Any]](func: F) -> F:
    """Mark a ``DependencyProvider`` method as a singleton factory."""
    factory: Any = func
    factory.__dependency_provider__ = _PROVIDE_MARKER
    return func


class DependencyProvider:
    """Base class for collections of dependency factory methods."""


@dataclass(frozen=True, slots=True)
class _Definition:
    dependency: type
    factory: Callable[..., Any]
    dependencies: Mapping[str, type]
    is_generator: bool
    is_async_generator: bool


class DependencyContainer:
    """Validated dependency graph containing one instance per type."""

    def __init__(self, *providers: DependencyProvider) -> None:
        self._definitions = MappingProxyType(self._collect(providers))
        self._validate_graph()
        self._stack = AsyncExitStack()
        self._values: dict[type, Any] = {}
        self._pending: dict[type, Any] = {}
        self._entered = False

    async def __aenter__(self) -> Self:
        if self._entered:
            raise RuntimeError("The dependency container is already active")
        self._entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        try:
            return await self._stack.__aexit__(exc_type, exc_value, traceback)
        finally:
            self._reset()

    async def aclose(self) -> None:
        """Close singleton resources and clear all resolved instances."""
        try:
            await self._stack.aclose()
        finally:
            self._reset()

    async def get[T](self, dependency: type[T]) -> T:
        """Resolve and cache one registered dependency."""
        definition = self._definitions.get(dependency)
        if definition is None:
            name = getattr(dependency, "__name__", repr(dependency))
            raise LookupError(f"No dependency provider is registered for '{name}'")
        return await self._resolve(dependency, lambda: self._create(definition))

    def has(self, dependency: type) -> bool:
        return dependency in self._definitions

    async def _resolve[T](
        self,
        dependency: type[T],
        factory: Callable[[], Any],
    ) -> T:
        if dependency in self._values:
            return self._values[dependency]
        pending = self._pending.get(dependency)
        if pending is not None:
            return await pending

        import asyncio

        future = asyncio.get_running_loop().create_future()
        self._pending[dependency] = future
        try:
            value = factory()
            value = await value if inspect.isawaitable(value) else value
            self._values[dependency] = value
            future.set_result(value)
            return value
        except BaseException as error:
            future.set_exception(error)
            future.exception()
            raise
        finally:
            self._pending.pop(dependency, None)

    async def _create(self, definition: _Definition) -> Any:
        kwargs = {
            name: await self.get(required)
            for name, required in definition.dependencies.items()
        }
        if definition.is_async_generator:
            manager = asynccontextmanager(definition.factory)(**kwargs)
            return await self._stack.enter_async_context(manager)
        if definition.is_generator:
            manager = _async_context_from_generator(definition.factory, kwargs)
            return await self._stack.enter_async_context(manager)
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
                if (
                    getattr(factory, "__dependency_provider__", None)
                    is not _PROVIDE_MARKER
                ):
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
                    is_generator=inspect.isgeneratorfunction(factory),
                    is_async_generator=inspect.isasyncgenfunction(factory),
                )
        return definitions

    def _validate_graph(self) -> None:
        for definition in self._definitions.values():
            for required in definition.dependencies.values():
                if required not in self._definitions:
                    name = getattr(required, "__name__", repr(required))
                    raise ValueError(
                        f"Missing dependency provider for '{name}', required by "
                        f"'{definition.dependency.__name__}'"
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

    def _reset(self) -> None:
        self._stack = AsyncExitStack()
        self._values.clear()
        self._pending.clear()
        self._entered = False


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
