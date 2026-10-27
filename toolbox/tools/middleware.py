import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from toolbox.dependency import DependencyContainer
from toolbox.tools.context import ToolContext
from toolbox.tools.models import Tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    raw_args: dict[str, Any]
    context: ToolContext | None = None
    tool: Tool | None = None
    container: DependencyContainer | None = None


type ToolHandler = Callable[[ToolCall], Awaitable[object]]


class ToolMiddleware:
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        raise NotImplementedError


class ErrorBoundaryMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        try:
            return await next(call)
        except Exception as error:
            logger.exception("Tool '%s' failed", call.name)
            message = str(error) or type(error).__name__
            return f"Tool failed: {message}"


class CallLoggingMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        logger.info("[tool] %s called with arguments: %r", call.name, call.raw_args)
        started = time.perf_counter()
        try:
            return await next(call)
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
