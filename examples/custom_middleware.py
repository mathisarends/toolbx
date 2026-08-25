import asyncio
import time

from agenttoolkit import CallLoggingMiddleware, ErrorBoundaryMiddleware, Tools
from agenttoolkit.tools.middleware import ToolCall, ToolHandler, ToolMiddleware


class TimingMiddleware(ToolMiddleware):
    async def __call__(self, call: ToolCall, next: ToolHandler) -> object:
        started = time.perf_counter()
        result = await next(call)
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"  [timing] {call.name} took {elapsed_ms:.2f}ms")
        return result


tools = Tools(
    middleware=(
        ErrorBoundaryMiddleware(),
        CallLoggingMiddleware(),
        TimingMiddleware(),
    )
)


@tools.register("Simulate slow work")
async def slow_task() -> str:
    await asyncio.sleep(0.05)
    return "done"


async def main() -> None:
    result = await tools.execute("slow_task")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
