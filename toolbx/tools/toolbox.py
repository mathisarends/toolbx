from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Collection, Iterator, Mapping, Sequence
from types import EllipsisType
from typing import Any

from toolbx.tools.arguments import resolve_arguments
from toolbx.tools.middleware import ToolCall, ToolMiddleware, ToolRequest, compose
from toolbx.tools.models import Tool
from toolbx.tools.schema import ToolSchema
from toolbx.tools.toolset import (
    ToolEntry,
    Toolset,
    collect_tool_entries,
    require_valid_name,
)

logger = logging.getLogger(__name__)


class Toolbox:
    """Register and execute toolsets with provider-neutral tool-call schemas."""

    def __init__(
        self,
        *toolsets: Toolset,
        middleware: Sequence[ToolMiddleware] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._middleware = tuple(middleware or ())
        self._handler = compose(self._middleware, self._invoke)
        for toolset in toolsets:
            self.add(toolset)

    def schemas(self) -> list[ToolSchema]:
        return [
            tool.to_schema() for tool in self._tools.values() if tool.is_available()
        ]

    def to_openai(self, *, strict: bool = False) -> list[dict[str, Any]]:
        return [schema.to_openai_schema(strict=strict) for schema in self.schemas()]

    def to_anthropic(self) -> list[dict[str, Any]]:
        return [schema.to_anthropic_schema() for schema in self.schemas()]

    def add(
        self,
        toolset: Toolset,
        *,
        namespace: str | EllipsisType | None = ...,
        include: Collection[str] | None = None,
        exclude: Collection[str] | None = None,
    ) -> tuple[Tool, ...]:
        """Atomically register the ``@tool`` methods of a toolset instance.

        The namespace defaults to the one declared by a ``Toolset``
        subclass; override it to register several instances of one class.
        ``include`` and ``exclude`` select tools by their local, unprefixed
        name.
        """
        if isinstance(toolset, type):
            raise TypeError("add expects an instance, not a class")
        if not isinstance(toolset, Toolset):
            raise TypeError("add expects a Toolset instance")
        toolset_type = type(toolset)
        if namespace is ...:
            namespace = toolset_type.namespace
        if namespace is not None:
            require_valid_name(namespace, "Namespace")
            if any(tool.namespace == namespace for tool in self._tools.values()):
                raise ValueError(
                    f"Toolset namespace '{namespace}' is already registered; "
                    "pass namespace= "
                    f"to register another {toolset_type.__name__} instance"
                )

        entries = collect_tool_entries(toolset_type)
        if not entries:
            raise ValueError(f"{toolset_type.__name__} does not define any tools")
        entries = _select_entries(toolset_type, entries, include, exclude)

        pending: list[Tool] = []
        collisions: list[str] = []
        for entry in entries:
            method = getattr(toolset, entry.attribute_name)
            definition = entry.definition
            exposed_name = (
                entry.local_name
                if namespace is None
                else f"{namespace}_{entry.local_name}"
            )
            existing = self._tools.get(exposed_name)
            if existing is not None:
                collisions.append(
                    f"Tool '{exposed_name}' is already registered "
                    f"(defined by {_describe_source(existing)})"
                )

            pending.append(
                Tool(
                    name=exposed_name,
                    description=definition.description,
                    fn=method,
                    params_model=definition.params,
                    tags=definition.tags,
                    metadata=definition.metadata,
                    requires_approval=definition.requires_approval,
                    available_when=definition.available_when,
                    namespace=namespace,
                    local_name=entry.local_name,
                )
            )
        if collisions:
            raise ValueError("; ".join(collisions))

        for registered_tool in pending:
            self._tools[registered_tool.name] = registered_tool
        return tuple(pending)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def remove(self, name: str) -> Tool:
        try:
            return self._tools.pop(name)
        except KeyError:
            raise KeyError(f"Unknown tool '{name}'") from None

    def subset(
        self,
        *,
        names: Collection[str] | None = None,
        tags: Collection[str] | None = None,
    ) -> Toolbox:
        """Return a new toolbox with the selected tools and the same middleware.

        A tool is selected when its name is in ``names`` or it carries any of
        ``tags``. Tools are shared, not copied, so they stay bound to the same
        toolset instances.
        """
        if isinstance(names, str) or isinstance(tags, str):
            raise TypeError("names and tags must be collections of strings")
        if names is None and tags is None:
            raise ValueError("subset needs names or tags")
        unknown = sorted(set(names or ()) - self._tools.keys())
        if unknown:
            raise ValueError(f"Unknown tools: {', '.join(unknown)}")
        wanted_names = set(names or ())
        wanted_tags = set(tags or ())
        selected = Toolbox(middleware=self._middleware)
        selected._tools = {
            name: tool
            for name, tool in self._tools.items()
            if name in wanted_names or tool.tags & wanted_tags
        }
        return selected

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | str | None = None,
        *,
        call_id: str | None = None,
    ) -> object:
        call = ToolCall(
            name=name,
            arguments=_parse_arguments(arguments),
            tool=self._tools.get(name),
            call_id=call_id,
        )
        return await self._handler(call)

    async def execute_many(
        self,
        calls: Sequence[ToolRequest],
        *,
        return_exceptions: bool = True,
    ) -> list[object]:
        """Execute calls concurrently, preserving input order and optional errors.

        By default, each failed call contributes its exception to the result
        list. Pass ``return_exceptions=False`` to propagate the first failure.
        Cancelling the batch cancels its outstanding calls.
        """
        return await asyncio.gather(
            *(
                self.execute(call.name, call.arguments, call_id=call.call_id)
                for call in calls
            ),
            return_exceptions=return_exceptions,
        )

    def merge(self, other: Toolbox, *, replace: bool = False) -> None:
        pending = {tool.name: tool for tool in other}
        collisions = self._tools.keys() & pending.keys()
        if collisions and not replace:
            raise ValueError(
                "; ".join(
                    f"Tool '{name}' already registered" for name in sorted(collisions)
                )
            )
        self._tools.update(pending)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __getitem__(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"Unknown tool '{name}'") from None

    async def _invoke(self, call: ToolCall) -> object:
        tool = call.tool
        if tool is None or not tool.is_available():
            if tool is not None:
                logger.debug(
                    "Tool '%s' is registered but currently unavailable", call.name
                )
            available = [
                candidate.name
                for candidate in self._tools.values()
                if candidate.is_available()
            ]
            raise LookupError(f"Unknown tool '{call.name}'. Available: {available}")

        params = tool.validate(call.arguments)
        arguments = resolve_arguments(tool, params)
        return await tool._invoke(arguments)


def _parse_arguments(arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments.strip() else {}
    if not isinstance(arguments, Mapping):
        raise TypeError("Tool arguments must be a JSON object or a mapping")
    return dict(arguments)


def _select_entries(
    toolset_type: type,
    entries: tuple[ToolEntry, ...],
    include: Collection[str] | None,
    exclude: Collection[str] | None,
) -> tuple[ToolEntry, ...]:
    if isinstance(include, str) or isinstance(exclude, str):
        raise TypeError("include and exclude must be collections of tool names")
    if include is None and exclude is None:
        return entries

    local_names = {entry.local_name for entry in entries}
    unknown = sorted((set(include or ()) | set(exclude or ())) - local_names)
    if unknown:
        raise ValueError(
            f"{toolset_type.__name__} has no tools named {', '.join(unknown)}"
        )
    selected = tuple(
        entry
        for entry in entries
        if (include is None or entry.local_name in include)
        and (exclude is None or entry.local_name not in exclude)
    )
    if not selected:
        raise ValueError(f"{toolset_type.__name__} selects no tools")
    return selected


def _describe_source(tool: Tool) -> str:
    owner = getattr(tool.fn, "__self__", None)
    return type(owner).__name__
