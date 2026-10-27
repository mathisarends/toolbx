import asyncio
import time

from toolbx import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    Toolbox,
    ToolCall,
    ToolHandler,
    Toolset,
    tool,
)


async def timing(call: ToolCall, call_next: ToolHandler) -> object:
    started = time.perf_counter()
    result = await call_next(call)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"  [timing] {call.name} took {elapsed_ms:.2f}ms")
    return result


class WorkTools(Toolset, namespace=None):
    @tool("Simulate slow work")
    async def slow_task(self) -> str:
        await asyncio.sleep(0.05)
        return "done"

    @tool("Fail on purpose")
    def broken(self) -> str:
        raise RuntimeError("disk full")


tools = WorkTools()
toolbox = Toolbox(
    toolsets=(tools,),
    middleware=[ErrorBoundaryMiddleware(), CallLoggingMiddleware(), timing],
)


async def main() -> None:
    print(await toolbox.call(tools.slow_task))
    # The error boundary turns the exception into text the model can read.
    print(await toolbox.call(tools.broken))


if __name__ == "__main__":
    asyncio.run(main())
