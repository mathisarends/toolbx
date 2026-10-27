from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from types import EllipsisType
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from agenttoolkit.dependency import DependencyContainer, DependencyProvider
from agenttoolkit.tools.arguments import resolve_arguments
from agenttoolkit.tools.binding import ToolAvailability, ToolDescription
from agenttoolkit.tools.context import _INJECT_MARKER, ToolContext
from agenttoolkit.tools.middleware import ToolCall, ToolMiddleware, compose
from agenttoolkit.tools.models import StatusFormatter, Tool, ToolMetadata
from agenttoolkit.tools.toolset import (
    AgentToolset,
    collect_tool_entries,
    require_valid_name,
)


class ToolRegistry:
    """Shared registration and execution support for tool representations."""

    def __init__(
        self,
        *,
        container: DependencyContainer | None = None,
        dependencies: Sequence[DependencyProvider] | None = None,
        context: ToolContext | None = None,
        middleware: Sequence[ToolMiddleware] | None = None,
    ) -> None:
        if container is not None and dependencies is not None:
            raise ValueError("Pass either container or dependencies, not both")
        self._tools: dict[str, Tool] = {}
        self._container = (
            DependencyContainer(*dependencies)
            if dependencies is not None
            else container
        )
        self._context = context
        self._handler = compose(middleware or (), self._invoke)

    def set_context(self, context: ToolContext | None) -> None:
        """Set the default context used for schemas and tool execution."""
        self._context = context

    def tool[ParamsT: BaseModel, **CallT, ResultT](
        self,
        description: str | ToolDescription | None = None,
        name: str | None = None,
        *,
        params: type[ParamsT] | None = None,
        status: StatusFormatter[ParamsT] | None = None,
        requires_approval: bool = False,
        available_when: ToolAvailability | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> Callable[
        [Callable[CallT, ResultT]],
        Callable[CallT, ResultT],
    ]:
        def decorator(
            func: Callable[CallT, ResultT],
        ) -> Callable[CallT, ResultT]:
            function_name = getattr(func, "__name__", type(func).__name__)
            self.register(
                Tool(
                    name=name or function_name,
                    description=description,
                    fn=func,
                    param_model=params,
                    metadata=ToolMetadata(
                        status=status,
                        tags=frozenset(tags),
                        extra=metadata or {},
                    ),
                    requires_approval=requires_approval,
                    available_when=available_when,
                )
            )
            return func

        return decorator

    def register(self, tool: Tool, *, replace: bool = False) -> Tool:
        """Register an existing tool and return it."""
        if tool.name in self._tools and not replace:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        return tool

    def add_plugin(self, plugin: object, *, name: str) -> tuple[Tool, ...]:
        """Atomically register decorated methods from a plugin instance."""
        require_valid_name(name, "Plugin name")
        return self.add(plugin, namespace=name)

    def add(
        self,
        toolset: object,
        *,
        namespace: str | EllipsisType | None = ...,
    ) -> tuple[Tool, ...]:
        """Atomically register the ``@tool`` methods of a toolset instance.

        The namespace defaults to the one declared by an ``AgentToolset``
        subclass; pass it to register several instances of one class or to
        register objects which are not ``AgentToolset`` subclasses.
        """
        if isinstance(toolset, type):
            raise TypeError("add expects an instance, not a class")
        toolset_type = type(toolset)
        if namespace is ...:
            if not isinstance(toolset, AgentToolset):
                raise TypeError(
                    f"{toolset_type.__name__} is not an AgentToolset; "
                    "pass namespace= to register it"
                )
            namespace = toolset_type.namespace
        if namespace is not None:
            require_valid_name(namespace, "Namespace")
            if any(tool.plugin_name == namespace for tool in self._tools.values()):
                raise ValueError(
                    f"Plugin '{namespace}' is already registered; pass namespace= "
                    f"to register another {toolset_type.__name__} instance"
                )

        entries = collect_tool_entries(toolset_type)
        if not entries:
            raise ValueError(f"{toolset_type.__name__} does not define any tools")

        pending: list[Tool] = []
        collisions: list[str] = []
        for entry in entries:
            method = getattr(toolset, entry.attribute_name)
            definition = entry.definition
            _reject_plugin_method_injection(entry.attribute_name, method)
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
                    param_model=definition.params,
                    metadata=ToolMetadata(
                        status=definition.status,
                        tags=frozenset(definition.tags),
                        extra=definition.metadata,
                    ),
                    requires_approval=definition.requires_approval,
                    available_when=definition.available_when,
                    plugin_name=namespace,
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

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        context: ToolContext | None = None,
    ) -> object:
        call = ToolCall(
            name=name,
            raw_args=dict(arguments or {}),
            context=self._context if context is None else context,
            tool=self._tools.get(name),
            container=self._container,
        )
        return await self._handler(call)

    def merge(self, other: ToolRegistry, *, replace: bool = False) -> None:
        for tool in other:
            self.register(tool, replace=replace)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    async def _invoke(self, call: ToolCall) -> object:
        tool = call.tool
        if tool is None or not tool.is_available(call.context):
            available = [
                candidate.name
                for candidate in self._tools.values()
                if candidate.is_available(call.context)
            ]
            raise LookupError(f"Unknown tool '{call.name}'. Available: {available}")

        params = tool.input_model.model_validate(call.raw_args)
        arguments = await resolve_arguments(tool, params, call.container, call.context)
        return await tool.execute(arguments)


def _describe_source(tool: Tool) -> str:
    owner = getattr(tool.fn, "__self__", None)
    if owner is None:
        return "a function tool"
    return type(owner).__name__


def _reject_plugin_method_injection(
    method_name: str,
    method: Callable[..., object],
) -> None:
    hints = get_type_hints(method, include_extras=True)
    for parameter_name, annotation in hints.items():
        if get_origin(annotation) is Annotated and _INJECT_MARKER in get_args(
            annotation
        ):
            raise TypeError(
                f"Plugin tool '{method_name}' cannot inject parameter "
                f"'{parameter_name}'; declare runtime dependencies on the "
                "plugin constructor"
            )
