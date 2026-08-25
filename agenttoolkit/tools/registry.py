from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from agenttoolkit.dependency import DependencyContainer, DependencyProvider
from agenttoolkit.tools.arguments import resolve_arguments
from agenttoolkit.tools.binding import ToolAvailability, ToolDescription
from agenttoolkit.tools.context import _INJECT_MARKER, ToolContext
from agenttoolkit.tools.middleware import ToolCall, ToolMiddleware, compose
from agenttoolkit.tools.models import StatusFormatter, Tool, ToolMetadata
from agenttoolkit.tools.plugins import ToolDefinition, get_tool_definition

_PLUGIN_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


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
        if isinstance(plugin, type):
            raise TypeError("add_plugin expects an instance, not a class")
        if not name or _PLUGIN_NAME.fullmatch(name) is None:
            raise ValueError(
                "Plugin name must contain only letters, numbers, '_' or '-'"
            )
        if any(tool.plugin_name == name for tool in self._tools.values()):
            raise ValueError(f"Plugin '{name}' is already registered")

        methods = _plugin_methods(plugin)
        if not methods:
            raise ValueError(f"Plugin '{name}' does not define any tools")

        pending: list[Tool] = []
        pending_names: set[str] = set()
        for method_name, method, definition in methods:
            _reject_plugin_method_injection(method_name, method)
            local_name = method_name if definition.name is None else definition.name
            if not local_name or _PLUGIN_NAME.fullmatch(local_name) is None:
                raise ValueError(
                    "Plugin tool name must contain only letters, numbers, '_' or '-'"
                )
            exposed_name = f"{name}_{local_name}"
            if exposed_name in pending_names:
                raise ValueError(
                    f"Plugin '{name}' defines duplicate tool '{local_name}'"
                )
            if exposed_name in self._tools:
                raise ValueError(f"Tool '{exposed_name}' is already registered")

            pending_names.add(exposed_name)
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
                    plugin_name=name,
                    local_name=local_name,
                )
            )

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


def _plugin_methods(
    plugin: object,
) -> list[tuple[str, Callable[..., object], ToolDefinition]]:
    plugin_type = type(plugin)
    attribute_names: list[str] = []
    for base in reversed(plugin_type.__mro__[:-1]):
        for attribute_name in vars(base):
            if attribute_name not in attribute_names:
                attribute_names.append(attribute_name)

    methods: list[tuple[str, Callable[..., object], ToolDefinition]] = []
    for attribute_name in attribute_names:
        descriptor = inspect.getattr_static(plugin_type, attribute_name)
        descriptor_definition = get_tool_definition(descriptor)
        if isinstance(descriptor, (classmethod, staticmethod)):
            definition = descriptor_definition or get_tool_definition(
                descriptor.__func__
            )
            if definition is not None:
                raise TypeError(
                    f"Plugin tool '{attribute_name}' must be an instance method"
                )
            continue

        definition = descriptor_definition
        if definition is None:
            continue
        method = getattr(plugin, attribute_name)
        if not inspect.ismethod(method):
            raise TypeError(
                f"Plugin tool '{attribute_name}' must be an instance method"
            )
        methods.append((attribute_name, method, definition))
    return methods


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
