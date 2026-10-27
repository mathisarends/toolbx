from __future__ import annotations

from collections.abc import Callable
from typing import Any

from toolbox.tools.context import ToolContext


class ToolDescription:
    def __init__(
        self,
        dependency: type,
        render: Callable[[Any], str],
        fallback: str,
    ) -> None:
        self._dependency = dependency
        self._render = render
        self._fallback = fallback

    def resolve(self, context: ToolContext | None) -> str:
        dependency = context.resolve(self._dependency) if context is not None else None
        return self._fallback if dependency is None else self._render(dependency)


class ToolAvailability:
    def __init__(self, predicate: Callable[[ToolContext | None], bool]) -> None:
        self._predicate = predicate

    def __call__(self, context: ToolContext | None) -> bool:
        return self._predicate(context)

    def __and__(self, other: ToolAvailability) -> ToolAvailability:
        return ToolAvailability(lambda context: self(context) and other(context))

    def __or__(self, other: ToolAvailability) -> ToolAvailability:
        return ToolAvailability(lambda context: self(context) or other(context))

    def __invert__(self) -> ToolAvailability:
        return ToolAvailability(lambda context: not self(context))


def description_from_context[T](
    dependency: type[T],
    *,
    render: Callable[[T], str],
    fallback: str,
) -> ToolDescription:
    return ToolDescription(dependency, render, fallback)


def provided(dependency: type) -> ToolAvailability:
    return ToolAvailability(
        lambda context: context is not None and context.resolve(dependency) is not None
    )


def requires[T](
    dependency: type[T],
    *,
    predicate: Callable[[T], bool],
) -> ToolAvailability:
    def is_available(context: ToolContext | None) -> bool:
        if context is None:
            return False
        resolved = context.resolve(dependency)
        return resolved is not None and predicate(resolved)

    return ToolAvailability(is_available)
