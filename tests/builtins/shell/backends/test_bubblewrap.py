from pathlib import Path

import pytest

import agenttoolkit.builtins.shell.backends.bubblewrap as bubblewrap_backend
from agenttoolkit.builtins.shell import (
    BubblewrapSandbox,
    CommandDefaults,
    CommandResult,
    SandboxPolicy,
)


@pytest.mark.asyncio
async def test_bubblewrap_executes_built_command_with_resolved_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    async def fake_run_process(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> CommandResult:
        calls.append((argv, kwargs))
        return CommandResult(str(kwargs["command"]), 0, "ok", "", 0.01)

    monkeypatch.setattr(
        BubblewrapSandbox,
        "available",
        property(lambda _: True),
    )
    monkeypatch.setattr(bubblewrap_backend, "run_process", fake_run_process)
    defaults = CommandDefaults(tmp_path, environment={"BASE": "one"})
    policy = SandboxPolicy.for_workspace(tmp_path)
    sandbox = BubblewrapSandbox(defaults=defaults, policy=policy)

    result = await sandbox.execute(
        "echo ok",
        env={"EXTRA": "two"},
        stdin="input",
        timeout=None,
    )

    assert result.ok
    assert sandbox.defaults is defaults
    assert sandbox.policy is policy
    argv, kwargs = calls[0]
    assert argv[-1] == "echo ok"
    assert ("--setenv", "EXTRA", "two") == argv[
        argv.index("EXTRA") - 1 : argv.index("EXTRA") + 2
    ]
    assert kwargs["stdin"] == "input"
    assert kwargs["timeout"] is None


def test_bubblewrap_rejects_missing_mount_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    sandbox = BubblewrapSandbox(
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy(readable_paths=(tmp_path, missing)),
    )

    with pytest.raises(FileNotFoundError, match="missing"):
        sandbox.build_argv("true")
