"""Expose polling-friendly background commands as agent tools."""

import asyncio
import sys
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from agenttoolkit import ToolRegistry, Tools
from agenttoolkit.builtins import (
    CommandDefaults,
    CommandJobManager,
    CommandJobSnapshot,
    LocalShellRunner,
)


class StartCommandParams(BaseModel):
    command: str = Field(description="Command to start in the background")
    timeout_seconds: float | None = Field(
        default=None,
        description="Maximum runtime in seconds; null disables the timeout",
    )


class JobParams(BaseModel):
    job_id: str = Field(description="Job ID returned by start_command")


def _response(snapshot: CommandJobSnapshot) -> dict[str, Any]:
    result = snapshot.result
    return {
        "job_id": snapshot.job_id,
        "state": snapshot.state,
        "done": snapshot.done,
        "output": snapshot.output,
        "error": snapshot.error,
        "exit_code": None if result is None else result.exit_code,
        "duration_seconds": None if result is None else result.duration_seconds,
        "output_truncated": False if result is None else result.output_truncated,
    }


def register_background_shell_tools(
    tools: ToolRegistry,
    jobs: CommandJobManager,
) -> None:
    @tools.register(
        "Start a command in the background and return a job ID immediately.",
        name="start_command",
        params=StartCommandParams,
        status=lambda params: f"Starting: {params.command}",
    )
    def start_command(params: StartCommandParams) -> dict[str, Any]:
        snapshot = jobs.start(
            params.command,
            timeout=params.timeout_seconds,
        )
        return _response(snapshot)

    @tools.register(
        "Poll a background command for status and output.",
        name="check_output",
        params=JobParams,
        status=lambda params: f"Checking command job {params.job_id}",
    )
    def check_output(params: JobParams) -> dict[str, Any]:
        return _response(jobs.check_output(params.job_id))

    @tools.register(
        "Cancel a running background command.",
        name="cancel_command",
        params=JobParams,
        status=lambda params: f"Cancelling command job {params.job_id}",
        requires_approval=True,
    )
    async def cancel_command(params: JobParams) -> dict[str, Any]:
        return _response(await jobs.cancel(params.job_id))


async def main() -> None:
    # The manager must live for at least as long as the agent session.
    runner = LocalShellRunner(
        CommandDefaults(working_directory=Path.cwd()),
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    tools = Tools()

    async with CommandJobManager(runner) as jobs:
        register_background_shell_tools(tools, jobs)

        started = cast(
            dict[str, Any],
            await tools.execute(
                "start_command",
                {
                    "command": "import time; time.sleep(0.1); print('build done')",
                    "timeout_seconds": None,
                },
            ),
        )
        print("started:", started)

        while True:
            polled = cast(
                dict[str, Any],
                await tools.execute(
                    "check_output",
                    {"job_id": started["job_id"]},
                ),
            )
            print("polled:", polled)
            if polled["done"]:
                break
            await asyncio.sleep(0.05)


if __name__ == "__main__":
    asyncio.run(main())
