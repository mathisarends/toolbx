import asyncio
import json
import threading

import pytest

from toolbx import Toolbox, ToolRequest, Toolset, tool


class Calls(Toolset, namespace=None):
    @tool("Echo")
    async def echo(self, value: int) -> int:
        return value

    @tool("Fail")
    async def fail(self) -> None:
        raise RuntimeError("failed")


@pytest.mark.asyncio
async def test_execute_accepts_json_and_preserves_the_call_id_in_middleware() -> None:
    seen = []

    async def record(call, call_next):
        seen.append((call.call_id, call.arguments))
        return await call_next(call)

    toolbox = Toolbox(toolsets=(Calls(),), middleware=[record])
    assert (
        await toolbox.execute(ToolRequest("echo", '{"value": "7"}', call_id="call-7"))
        == 7
    )
    assert seen == [("call-7", {"value": "7"})]
    with pytest.raises(json.JSONDecodeError):
        await toolbox.execute(ToolRequest("echo", "invalid JSON"))
    for arguments in ("[1, 2]", "null", "3", "true"):
        with pytest.raises(TypeError, match="JSON object"):
            await toolbox.execute(ToolRequest("echo", arguments))


@pytest.mark.asyncio
async def test_parallel_calls_overlap_and_keep_order_and_individual_errors() -> None:
    both_started = asyncio.Event()
    started = []

    class Parallel(Toolset, namespace=None):
        @tool("Wait for the other call")
        async def wait(self, value: int) -> int:
            started.append(value)
            if len(started) == 2:
                both_started.set()
            await both_started.wait()
            return value

    toolbox = Toolbox(
        toolsets=(
            Calls(),
            Parallel(),
        )
    )
    results = await asyncio.wait_for(
        toolbox.execute_many(
            [
                ToolRequest("wait", {"value": 2}, "a"),
                ToolRequest("fail", call_id="b"),
                ToolRequest("wait", '{"value": 1}', "c"),
                ToolRequest("missing", call_id="d"),
            ]
        ),
        timeout=2,
    )
    assert results[0] == 2
    assert isinstance(results[1], RuntimeError)
    assert results[2] == 1
    assert isinstance(results[3], LookupError)
    assert await toolbox.execute_many([]) == []
    with pytest.raises(RuntimeError, match="failed"):
        await toolbox.execute_many([ToolRequest("fail")], return_exceptions=False)


@pytest.mark.asyncio
async def test_cancelling_a_batch_cancels_its_outstanding_calls() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class Waiting(Toolset, namespace=None):
        @tool("Wait")
        async def wait(self) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    batch = asyncio.create_task(
        Toolbox(toolsets=(Waiting(),)).execute_many([ToolRequest("wait")])
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    batch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await batch
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_blocking_sync_calls_run_in_parallel_without_blocking_the_loop() -> None:
    barrier = threading.Barrier(2, timeout=2)

    class Blocking(Toolset, namespace=None):
        @tool("Wait for another worker")
        def wait(self, value: int) -> int:
            barrier.wait()
            return value

    results = await asyncio.wait_for(
        Toolbox(toolsets=(Blocking(),)).execute_many(
            [ToolRequest("wait", {"value": 1}), ToolRequest("wait", {"value": 2})]
        ),
        timeout=3,
    )
    assert results == [1, 2]
