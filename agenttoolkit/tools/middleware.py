import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from agenttoolkit.dependency import DependencyContainer
from agenttoolkit.skills import Skills
from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.models import Tool

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
            return f"Tool failed: {error}"


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


class SkillRefreshMiddleware(ToolMiddleware):
    async def __call__(
        self,
        call: ToolCall,
        next: ToolHandler,
    ) -> object:
        try:
            return await next(call)
        finally:
            if call.tool is not None:
                if call.container is not None and call.container.has(Skills):
                    skills = await call.container.get(Skills)
                else:
                    skills = (
                        None if call.context is None else call.context.resolve(Skills)
                    )
                if skills is not None:
                    try:
                        skills.refresh_if_changed()
                    except ValueError:
                        logger.exception(
                            "Skill refresh failed after tool '%s'; "
                            "keeping the active registry.",
                            call.name,
                        )


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
