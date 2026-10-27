import asyncio
import time

from toolbx import CallLoggingMiddleware, ErrorBoundaryMiddleware, Toolbox, Toolset
from toolbx import tool as mark_tool
from toolbx.tools.middleware import ToolCall, ToolHandler, ToolMiddleware


class TimingMiddleware(ToolMiddleware):
    async def __call__(self, call: ToolCall, call_next: ToolHandler) -> object:
        started = time.perf_counter()
        result = await call_next(call)
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"  [timing] {call.name} took {elapsed_ms:.2f}ms")
        return result


toolbox = Toolbox(
    middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware(), TimingMiddleware())
)


class DefinedTools1(Toolset, namespace=None):
    @mark_tool("Simulate slow work")
    async def slow_task(self) -> str:
        await asyncio.sleep(0.05)
        return "done"


toolbox.add(DefinedTools1())


async def main() -> None:
    result = await toolbox.execute("slow_task")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
