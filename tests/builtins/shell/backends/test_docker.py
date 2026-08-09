from collections.abc import Callable
from pathlib import Path

import pytest

from agenttoolkit.builtins.shell import (
    CommandDefaults,
    CommandExecutionError,
    CommandResult,
    DockerSandbox,
    DockerSandboxStateError,
    SandboxPolicy,
)


@pytest.mark.asyncio
async def test_docker_validates_public_operations_before_execution(
    tmp_path: Path,
) -> None:
    policy = SandboxPolicy.for_workspace(tmp_path)
    defaults = CommandDefaults(tmp_path)
    sandbox = DockerSandbox("image", defaults=defaults, policy=policy)

    assert sandbox.policy is policy
    assert sandbox.defaults is defaults
    await sandbox.close()

    with pytest.raises(ValueError, match="command must not be empty"):
        await sandbox.execute("")
    with pytest.raises(ValueError, match="command must not be empty"):
        sandbox.build_exec_argv("")
    with pytest.raises(DockerSandboxStateError, match="not open"):
        sandbox.build_exec_argv("true")
    with pytest.raises(PermissionError, match="not mounted"):
        sandbox.container_path(tmp_path.parent / "outside")


@pytest.mark.asyncio
async def test_docker_removes_container_after_failed_start(
    tmp_path: Path,
    docker_process: Callable[..., object],
) -> None:
    failed = CommandResult("open", 125, "", "daemon rejected image", 0.1)
    process = docker_process(failed)
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )

    with pytest.raises(CommandExecutionError, match="daemon rejected image"):
        await sandbox.open()

    assert not sandbox.is_open
    assert [call[1] for call in process.calls] == ["run", "rm"]


@pytest.mark.asyncio
async def test_docker_removes_container_after_unexpected_open_error(
    tmp_path: Path,
    docker_process: Callable[..., object],
) -> None:
    process = docker_process(RuntimeError("transport broke"))
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )

    with pytest.raises(RuntimeError, match="transport broke"):
        await sandbox.open()

    assert not sandbox.is_open
    assert [call[1] for call in process.calls] == ["run", "rm"]


@pytest.mark.asyncio
async def test_docker_discards_container_after_unexpected_command_error(
    tmp_path: Path,
    docker_process: Callable[..., object],
) -> None:
    process = docker_process(
        CommandResult("open", 0, "container-id", "", 0.1),
        RuntimeError("exec transport broke"),
    )
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )
    await sandbox.open()

    with pytest.raises(RuntimeError, match="exec transport broke"):
        await sandbox.execute("true")

    assert not sandbox.is_open
    assert [call[1] for call in process.calls] == ["run", "exec", "rm"]


@pytest.mark.asyncio
async def test_docker_exec_environment_is_validated(
    tmp_path: Path,
    docker_process: Callable[..., object],
) -> None:
    docker_process(CommandResult("open", 0, "container-id", "", 0.1))
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )

    async with sandbox:
        with pytest.raises(ValueError, match="variable name"):
            sandbox.build_exec_argv("true", env={"BAD=NAME": "value"})
        with pytest.raises(ValueError, match="contains NUL"):
            sandbox.build_exec_argv("true", env={"NAME": "bad\0value"})
