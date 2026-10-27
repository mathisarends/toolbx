from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, get_type_hints

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


class DependencyContainer:
    """Validated dependency graph containing one instance per type."""

    def __init__(self, *providers: DependencyProvider) -> None:
        self._definitions = MappingProxyType(self._collect(providers))
        self._validate_graph()
        self._values: dict[type, Any] = {}
        self._pending: dict[type, Any] = {}

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
                if inspect.isgeneratorfunction(factory) or inspect.isasyncgenfunction(
                    factory
                ):
                    factory_name = getattr(factory, "__name__", type(factory).__name__)
                    raise TypeError(
                        f"Dependency provider '{factory_name}' cannot be a generator; "
                        "the application must own resource lifecycles"
                    )
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


def _provided_type(annotation: Any, factory: Callable[..., Any]) -> type:
    factory_name = getattr(factory, "__name__", type(factory).__name__)
    if annotation is None:
        raise TypeError(f"Dependency provider '{factory_name}' needs a return type")
    return annotation
