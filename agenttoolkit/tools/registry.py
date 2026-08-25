from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from agenttoolkit.tools.arguments import resolve_arguments
from agenttoolkit.tools.binding import ToolAvailability, ToolDescription
from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.middleware import ToolCall, ToolMiddleware, compose
from agenttoolkit.tools.models import StatusFormatter, Tool, ToolMetadata


class ToolRegistry:
    """Shared registration and execution support for tool representations."""

    def __init__(
        self,
        *,
        context: ToolContext | None = None,
        middleware: Sequence[ToolMiddleware] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
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

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        context: ToolContext | None = None,
    ) -> object:
        return await self._handler(
            ToolCall(
                name=name,
                raw_args=dict(arguments or {}),
                context=self._context if context is None else context,
                tool=self._tools.get(name),
            )
        )

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
        arguments = resolve_arguments(tool, params, call.context)
        return await tool.execute(arguments)
