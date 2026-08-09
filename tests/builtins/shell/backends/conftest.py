from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

import agenttoolkit.builtins.shell.backends.docker as docker_backend
from agenttoolkit.builtins.shell import CommandResult


@dataclass
class ProcessScript:
    outcomes: list[CommandResult | BaseException] = field(default_factory=list)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    async def __call__(
        self,
        argv: tuple[str, ...],
        **kwargs: Any,
    ) -> CommandResult:
        self.calls.append(argv)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is not None:
            return outcome
        return CommandResult(str(kwargs["command"]), 0, "", "", 0.01)


@pytest.fixture
def docker_process(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., ProcessScript]:
    def install(*outcomes: CommandResult | BaseException) -> ProcessScript:
        script = ProcessScript(list(outcomes))
        monkeypatch.setattr(docker_backend, "run_process", script)
        return script

    return install
