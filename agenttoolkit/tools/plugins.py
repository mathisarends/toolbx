from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from agenttoolkit.tools.binding import ToolAvailability, ToolDescription

_TOOL_DEFINITION_ATTRIBUTE = "__agenttoolkit_tool_definition__"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Metadata attached to a method before its plugin is registered."""

    description: str | ToolDescription | None
    name: str | None
    params: type[BaseModel] | None
    requires_approval: bool
    available_when: ToolAvailability | None
    tags: tuple[str, ...]
    metadata: Mapping[str, Any]


def tool[ParamsT: BaseModel, **CallT, ResultT](
    description: str | ToolDescription | None = None,
    name: str | None = None,
    *,
    params: type[ParamsT] | None = None,
    requires_approval: bool = False,
    available_when: ToolAvailability | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> Callable[
    [Callable[CallT, ResultT]],
    Callable[CallT, ResultT],
]:
    """Mark an instance method for registration as part of a plugin."""

    definition = ToolDefinition(
        description=description,
        name=name,
        params=params,
        requires_approval=requires_approval,
        available_when=available_when,
        tags=tuple(tags),
        metadata=MappingProxyType(dict(metadata or {})),
    )

    def decorator(
        func: Callable[CallT, ResultT],
    ) -> Callable[CallT, ResultT]:
        setattr(func, _TOOL_DEFINITION_ATTRIBUTE, definition)
        return func

    return decorator


def get_tool_definition(value: object) -> ToolDefinition | None:
    definition = getattr(value, _TOOL_DEFINITION_ATTRIBUTE, None)
    return definition if isinstance(definition, ToolDefinition) else None
