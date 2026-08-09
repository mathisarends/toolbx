import asyncio
from pathlib import Path

import pytest

import agenttoolkit.builtins.shell.backends.docker as docker_backend
from agenttoolkit.builtins.shell import (
    CommandDefaults,
    CommandJobManager,
    CommandJobNotFoundError,
    CommandJobState,
    CommandJobStateError,
    CommandResult,
    DockerSandbox,
    SandboxPolicy,
)


@pytest.mark.asyncio
async def test_command_jobs_start_poll_finish_and_forget(controlled_runner) -> None:
    runner = controlled_runner
    async with CommandJobManager(runner) as jobs:
        started = jobs.start("build", timeout=None)
        assert started.state is CommandJobState.RUNNING
        assert not started.done
        assert started.output == ""

        await runner.started.wait()
        assert runner.timeout is None
        assert jobs.check_output(started.job_id).state is CommandJobState.RUNNING

        runner.release.set()
        await asyncio.sleep(0)
        finished = jobs.check_output(started.job_id)
        assert finished.state is CommandJobState.SUCCEEDED
        assert finished.done
        assert finished.output == "finished\n"

        jobs.forget(started.job_id)
        with pytest.raises(CommandJobNotFoundError, match="unknown command job"):
            jobs.check_output(started.job_id)


@pytest.mark.asyncio
async def test_command_jobs_cancel_and_close(controlled_runner) -> None:
    runner = controlled_runner
    jobs = CommandJobManager(runner)
    first = jobs.start("train")
    await runner.started.wait()

    cancelled = await jobs.cancel(first.job_id)
    assert cancelled.state is CommandJobState.CANCELLED

    await jobs.close()
    await jobs.close()
    with pytest.raises(CommandJobStateError, match="closed"):
        jobs.start("another")
    with pytest.raises(CommandJobStateError, match="closed"):
        await jobs.__aenter__()


@pytest.mark.asyncio
async def test_command_jobs_validate_lifecycle_operations(controlled_runner) -> None:
    runner = controlled_runner
    jobs = CommandJobManager(runner)

    with pytest.raises(ValueError, match="must not be empty"):
        jobs.start("")

    started = jobs.start("long-running")
    await runner.started.wait()
    with pytest.raises(CommandJobStateError, match="cannot forget"):
        jobs.forget(started.job_id)

    await jobs.close()
    with pytest.raises(CommandJobNotFoundError, match="unknown command job"):
        jobs.check_output(started.job_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "expected_state"),
    [
        (
            CommandResult("timeout", -1, "partial", "", 1.0, timed_out=True),
            CommandJobState.TIMED_OUT,
        ),
        (
            CommandResult("failure", 7, "", "bad", 0.1),
            CommandJobState.FAILED,
        ),
    ],
)
async def test_command_jobs_preserve_unsuccessful_results(
    result: CommandResult,
    expected_state: CommandJobState,
    immediate_runner,
) -> None:
    jobs = CommandJobManager(immediate_runner(result))
    started = jobs.start(result.command)
    await asyncio.sleep(0)

    snapshot = jobs.check_output(started.job_id)
    assert snapshot.state is expected_state
    assert snapshot.result is result
    assert snapshot.output == result.output

    # Cancelling an already completed job preserves its terminal state.
    assert (await jobs.cancel(started.job_id)).state is expected_state
    await jobs.close()


@pytest.mark.asyncio
async def test_command_jobs_report_runner_exceptions(immediate_runner) -> None:
    jobs = CommandJobManager(immediate_runner(error=RuntimeError("runner broke")))
    started = jobs.start("explode")
    await asyncio.sleep(0)

    snapshot = jobs.check_output(started.job_id)
    assert snapshot.state is CommandJobState.FAILED
    assert snapshot.result is None
    assert snapshot.error == "RuntimeError: runner broke"
    await jobs.close()


@pytest.mark.asyncio
async def test_docker_allows_concurrent_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exec_started = 0
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_process(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> CommandResult:
        nonlocal exec_started
        if argv[1] == "exec":
            exec_started += 1
            if exec_started == 2:
                both_started.set()
            await release.wait()
        return CommandResult(str(kwargs["command"]), 0, "ok", "", 0.01)

    monkeypatch.setattr(docker_backend, "run_process", fake_run_process)
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )

    async with sandbox:
        first = asyncio.create_task(sandbox.execute("first"))
        second = asyncio.create_task(sandbox.execute("second"))
        await asyncio.wait_for(both_started.wait(), timeout=1)
        release.set()
        results = await asyncio.gather(first, second)

    assert exec_started == 2
    assert all(result.ok for result in results)
