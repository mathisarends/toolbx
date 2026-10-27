import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from toolbx.tools.models import Tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Provider-neutral request for a tool call, including an optional trace ID."""

    name: str
    arguments: Mapping[str, Any] | str | None = None
    call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    tool: Tool | None = None
    call_id: str | None = None


type ToolHandler = Callable[[ToolCall], Awaitable[object]]


class ToolMiddleware(Protocol):
    async def __call__(
        self,
        call: ToolCall,
        call_next: ToolHandler,
        /,
    ) -> object: ...


class ErrorBoundaryMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        call_next: ToolHandler,
    ) -> object:
        try:
            return await call_next(call)
        except Exception as error:
            logger.exception("Tool '%s' failed", call.name)
            message = str(error) or type(error).__name__
            return f"Tool failed: {message}"


class CallLoggingMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        call_next: ToolHandler,
    ) -> object:
        logger.info("[tool] %s called", call.name)
        logger.debug("[tool] %s arguments: %r", call.name, call.arguments)
        started = time.perf_counter()
        try:
            return await call_next(call)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info("[tool] %s finished (%.0f ms)", call.name, elapsed_ms)


def compose(
    middlewares: Sequence[ToolMiddleware],
    handler: ToolHandler,
) -> ToolHandler:
    for middleware in reversed(middlewares):
        handler = _wrap(middleware, handler)
    return handler


def _wrap(middleware: ToolMiddleware, next_handler: ToolHandler) -> ToolHandler:
    async def handler(call: ToolCall) -> object:
        return await middleware(call, next_handler)

    return handler
