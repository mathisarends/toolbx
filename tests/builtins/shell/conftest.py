import asyncio
import os
from collections.abc import Callable, Mapping

import pytest

from agenttoolkit.builtins.shell import (
    DEFAULT_TIMEOUT,
    CommandResult,
    CommandTimeout,
)


class ControlledRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.timeout: CommandTimeout = DEFAULT_TIMEOUT

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: CommandTimeout = DEFAULT_TIMEOUT,
    ) -> CommandResult:
        self.timeout = timeout
        self.started.set()
        await self.release.wait()
        return CommandResult(command, 0, "finished\n", "", 0.01)


class ImmediateRunner:
    def __init__(
        self,
        result: CommandResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error

    async def execute(
        self,
        command: str,
        **_: object,
    ) -> CommandResult:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@pytest.fixture
def controlled_runner() -> ControlledRunner:
    return ControlledRunner()


@pytest.fixture
def immediate_runner() -> Callable[..., ImmediateRunner]:
    return ImmediateRunner
