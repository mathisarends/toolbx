import sys
from pathlib import Path, PurePosixPath

import pytest

import agenttoolkit.builtins.shell.backends.docker as docker_backend
from agenttoolkit.builtins.shell import (
    BindMount,
    BubblewrapSandbox,
    CommandDefaults,
    CommandExecutionError,
    CommandLimits,
    CommandResult,
    CommandRunner,
    CommandUnavailableError,
    DockerSandbox,
    DockerSandboxStateError,
    LocalShellRunner,
    SandboxLimits,
    SandboxPolicy,
)
from agenttoolkit.builtins.shell.command import _format_bytes, run_process


def test_policy_normalizes_isolation_paths_and_network(tmp_path: Path) -> None:
    policy = SandboxPolicy.for_workspace(
        tmp_path,
        enable_network_access=True,
    )

    assert policy.enable_network_access
    assert policy.allows_read(tmp_path / "child")
    assert policy.allows_write(tmp_path / "child")
    readonly = SandboxPolicy(
        readable_paths=(tmp_path, tmp_path),
        enable_network_access=False,
    )
    assert not readonly.enable_network_access
    assert len(readonly.readable_paths) == 1
    assert not readonly.allows_write(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("memory_bytes", 0),
        ("pids", -2),
        ("cpus", 0),
    ],
)
def test_limits_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        SandboxLimits(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [("timeout_seconds", 0), ("max_output_bytes", -1)],
)
def test_command_limits_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        CommandLimits(**{field: value})


def test_command_defaults_validate_environment_and_working_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="variable name"):
        CommandDefaults(environment={"BAD=NAME": "value"})
    with pytest.raises(ValueError, match="contains NUL"):
        CommandDefaults(environment={"NAME": "bad\0value"})

    root = tmp_path / "root"
    root.mkdir()
    defaults = CommandDefaults(root, environment={"COUNT": "2"})
    assert defaults.environment["COUNT"] == "2"
    assert defaults.select_working_directory() == root.resolve()
    child = root / "child"
    child.mkdir()
    assert defaults.select_working_directory("child") == child.resolve()
    with pytest.raises(NotADirectoryError):
        defaults.select_working_directory("missing")


def test_policy_rejects_unreadable_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    policy = SandboxPolicy.for_workspace(root)
    with pytest.raises(PermissionError, match="not readable"):
        policy.require_readable(tmp_path / "outside")


def test_command_result_helpers() -> None:
    success = CommandResult("true", 0, "out", "err", 0.1)
    assert success.ok
    assert success.exit_code == 0
    assert success.output == "out\nerr"
    assert success.check_returncode() is success

    failure = CommandResult("false", 2, "", "bad", 0.1)
    with pytest.raises(CommandExecutionError, match="status 2: bad"):
        failure.check_returncode()

    timeout = CommandResult("wait", -1, "", "", 1.0, timed_out=True)
    with pytest.raises(CommandExecutionError, match="timed out"):
        timeout.check_returncode()

    assert CommandResult("stdout", 0, "out", "", 0.1).output == "out"
    assert CommandResult("stderr", 0, "", "err", 0.1).output == "err"
    assert CommandResult("joined", 0, "out\n", "err", 0.1).output == "out\nerr"

    empty_failure = CommandResult("false", 1, "", "", 0.1)
    with pytest.raises(CommandExecutionError, match=r"status 1$"):
        empty_failure.check_returncode()


@pytest.mark.parametrize(
    ("count", "formatted"),
    [
        (12, "12 B"),
        (2 * 1024, "2.0 KB"),
        (3 * 1024**2, "3.0 MB"),
        (4 * 1024**3, "4.0 GB"),
    ],
)
def test_output_omission_sizes_are_human_readable(
    count: int,
    formatted: str,
) -> None:
    assert _format_bytes(count) == formatted


@pytest.mark.asyncio
async def test_run_process_validates_its_direct_contract(tmp_path: Path) -> None:
    arguments = {
        "command": "noop",
        "cwd": tmp_path,
        "env": None,
        "stdin": None,
        "timeout": None,
        "max_output_bytes": None,
    }
    with pytest.raises(ValueError, match="argv must not be empty"):
        await run_process((), **arguments)
    with pytest.raises(ValueError, match="timeout must be positive"):
        await run_process((sys.executable,), **(arguments | {"timeout": 0}))


@pytest.mark.asyncio
async def test_local_shell_runner_executes_and_enforces_output_limit(
    tmp_path: Path,
) -> None:
    defaults = CommandDefaults(
        tmp_path,
        environment={"FROM_POLICY": "yes"},
        limits=CommandLimits(timeout_seconds=2, max_output_bytes=4),
    )
    runner = LocalShellRunner(
        defaults,
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    assert isinstance(runner, CommandRunner)
    result = await runner.execute(
        "import os,sys; print(os.environ['FROM_POLICY']); "
        "print(os.environ['EXTRA']); print(sys.stdin.read())",
        env={"EXTRA": "ok"},
        stdin="input",
    )
    assert result.ok
    assert result.output_truncated
    assert result.stdout_omitted_bytes > 0
    assert "omitted" in result.stdout
    assert result.spill_paths == ()


@pytest.mark.asyncio
async def test_capture_keeps_both_ends_and_isolates_stream_budgets(
    tmp_path: Path,
) -> None:
    runner = LocalShellRunner(
        CommandDefaults(
            tmp_path,
            limits=CommandLimits(timeout_seconds=10, max_output_bytes=64),
        ),
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    result = await runner.execute(
        "import sys; sys.stdout.write('START' + 'x' * 5000 + 'END'); "
        "sys.stderr.write('failure reason')"
    )

    assert result.stdout.startswith("START")
    assert result.stdout.endswith("END")
    # A chatty stdout must not consume the budget that stderr needs.
    assert result.stderr == "failure reason"
    assert result.stderr_omitted_bytes == 0


@pytest.mark.asyncio
async def test_unbounded_capture_keeps_everything(tmp_path: Path) -> None:
    runner = LocalShellRunner(
        CommandDefaults(
            tmp_path,
            limits=CommandLimits(timeout_seconds=10, max_output_bytes=None),
        ),
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    result = await runner.execute("import sys; sys.stdout.write('a' * 5000)")

    assert result.stdout == "a" * 5000
    assert not result.output_truncated


@pytest.mark.asyncio
async def test_spill_directory_preserves_full_output(tmp_path: Path) -> None:
    spill = tmp_path / "overflow"
    runner = LocalShellRunner(
        CommandDefaults(
            tmp_path,
            limits=CommandLimits(timeout_seconds=10, max_output_bytes=64),
            spill_directory=spill,
        ),
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    result = await runner.execute("import sys; sys.stdout.write('a' * 5000)")

    assert result.stdout_spill_path is not None
    assert result.stdout_spill_path.read_bytes() == b"a" * 5000
    assert str(result.stdout_spill_path) in result.stdout
    # stderr stayed inside its budget, so no file was created for it.
    assert result.stderr_spill_path is None


@pytest.mark.asyncio
async def test_spill_directory_untouched_without_overflow(tmp_path: Path) -> None:
    spill = tmp_path / "overflow"
    runner = LocalShellRunner(
        CommandDefaults(
            tmp_path,
            limits=CommandLimits(timeout_seconds=10, max_output_bytes=4096),
            spill_directory=spill,
        ),
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    result = await runner.execute("print('small')")

    assert result.stdout.strip() == "small"
    assert not result.output_truncated
    assert not spill.exists()


@pytest.mark.asyncio
async def test_local_shell_runner_timeout_errors_and_validation(
    tmp_path: Path,
) -> None:
    runner = LocalShellRunner(
        CommandDefaults(tmp_path, limits=CommandLimits(timeout_seconds=0.01)),
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    result = await runner.execute("import time; time.sleep(1)")
    assert result.timed_out
    assert not result.ok

    no_timeout = await runner.execute("import time; time.sleep(0.02)", timeout=None)
    assert no_timeout.ok

    with pytest.raises(ValueError, match="must not be empty"):
        await runner.execute("")
    with pytest.raises(ValueError, match="positive"):
        await runner.execute("pass", timeout=0)

    missing = LocalShellRunner(shell="definitely-not-an-executable")
    with pytest.raises(CommandUnavailableError, match="executable not found"):
        await missing.execute("echo ok", cwd=tmp_path)


def test_docker_builds_a_hardened_command(tmp_path: Path) -> None:
    extra = tmp_path / "read"
    extra.mkdir()
    policy = SandboxPolicy(
        readable_paths=(extra,),
        writable_paths=(tmp_path,),
        enable_network_access=False,
        limits=SandboxLimits(memory_bytes=1024, pids=8, cpus=0.5),
    )
    sandbox = DockerSandbox(
        "python:3.14",
        defaults=CommandDefaults(tmp_path, environment={"BASE": "one"}),
        policy=policy,
    )
    argv = sandbox.build_open_argv(container_name="test-sandbox")

    assert argv[:4] == ("docker", "run", "--detach", "--rm")
    assert "--read-only" in argv
    assert ("--network", "none") == argv[
        argv.index("--network") : argv.index("--network") + 2
    ]
    assert "--memory" in argv
    assert "--pids-limit" in argv
    assert "--cpus" in argv
    assert "BASE=one" in argv
    assert argv[-3:] == (
        "/bin/sh",
        "-c",
        "while :; do sleep 3600; done",
    )
    assert str(sandbox.container_path("read")) == "/mnt/path-0"


def test_docker_supports_named_mounts_inherited_environment_and_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setenv("CLI_TOKEN", "secret")
    monkeypatch.setattr(docker_backend.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(docker_backend.os, "getgid", lambda: 1001, raising=False)

    config_mount = BindMount.read_only(config, "/home/agent/.config/my-cli")
    output_mount = BindMount.read_write(output, "/output")
    sandbox = DockerSandbox(
        "cli:latest",
        defaults=CommandDefaults(workspace),
        policy=SandboxPolicy.for_workspace(workspace),
        mounts=(config_mount, output_mount),
        inherit_environment=("CLI_TOKEN", "CLI_TOKEN"),
        user="host",
    )
    argv = sandbox.build_open_argv(container_name="test-sandbox")

    assert sandbox.mounts == (config_mount, output_mount)
    assert sandbox.inherit_environment == ("CLI_TOKEN",)
    assert sandbox.user == "host"
    assert ("--env", "CLI_TOKEN") == argv[argv.index("--env") : argv.index("--env") + 2]
    assert "CLI_TOKEN=secret" not in argv
    assert ("--user", "1000:1001") == argv[
        argv.index("--user") : argv.index("--user") + 2
    ]
    assert (
        f"type=bind,src={config.resolve()},dst=/home/agent/.config/my-cli,readonly"
    ) in argv
    assert f"type=bind,src={output.resolve()},dst=/output" in argv
    assert sandbox.container_path(config / "settings.json") == PurePosixPath(
        "/home/agent/.config/my-cli/settings.json"
    )
    assert sandbox.container_path(output / "artifact.txt") == PurePosixPath(
        "/output/artifact.txt"
    )


def test_docker_supports_an_explicit_network_mode(tmp_path: Path) -> None:
    sandbox = DockerSandbox(
        "cli:latest",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path, enable_network_access=True),
        network_mode="host",
    )

    argv = sandbox.build_open_argv(container_name="test-sandbox")

    assert sandbox.network_mode == "host"
    assert ("--network", "host") == argv[
        argv.index("--network") : argv.index("--network") + 2
    ]


def test_docker_validates_convenience_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()

    with pytest.raises(ValueError, match="absolute container path"):
        BindMount.read_only(first, "relative")
    with pytest.raises(ValueError, match="below '/'"):
        BindMount.read_write(first, "/")
    with pytest.raises(ValueError, match="source is configured more than once"):
        DockerSandbox(
            "image",
            mounts=(
                BindMount.read_only(first, "/first"),
                BindMount.read_only(first, "/other"),
            ),
        )
    with pytest.raises(ValueError, match="target is configured more than once"):
        DockerSandbox(
            "image",
            mounts=(
                BindMount.read_only(first, "/shared"),
                BindMount.read_only(second, "/shared"),
            ),
        )
    with pytest.raises(ValueError, match="variable name"):
        DockerSandbox("image", inherit_environment=("BAD=NAME",))
    with pytest.raises(ValueError, match="user"):
        DockerSandbox("image", user=" ")
    with pytest.raises(ValueError, match="'bridge' or 'host'"):
        DockerSandbox("image", network_mode="invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="requires network access"):
        DockerSandbox("image", network_mode="host")

    monkeypatch.delenv("MISSING_CLI_TOKEN", raising=False)
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(workspace),
        policy=SandboxPolicy.for_workspace(workspace),
        inherit_environment=("MISSING_CLI_TOKEN",),
    )
    with pytest.raises(ValueError, match="MISSING_CLI_TOKEN"):
        sandbox.build_open_argv()

    collision = DockerSandbox(
        "image",
        defaults=CommandDefaults(workspace),
        policy=SandboxPolicy.for_workspace(workspace),
        mounts=(BindMount.read_only(first, "/workspace"),),
    )
    with pytest.raises(ValueError, match="used by both"):
        collision.build_open_argv()


def test_docker_validates_image_mounts_and_default_cwd(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="image"):
        DockerSandbox(" ")

    missing = tmp_path / "missing"
    policy = SandboxPolicy(readable_paths=(tmp_path, missing))
    with pytest.raises(FileNotFoundError):
        DockerSandbox(
            "image",
            defaults=CommandDefaults(tmp_path),
            policy=policy,
        ).build_open_argv()


@pytest.mark.asyncio
async def test_docker_cleans_up_a_timed_out_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run_process(
        argv: tuple[str, ...],
        **_: object,
    ) -> CommandResult:
        calls.append(argv)
        return CommandResult(
            "command",
            -1 if argv[1] == "exec" else 0,
            "",
            "",
            1,
            timed_out=argv[1] == "exec",
        )

    monkeypatch.setattr(docker_backend, "run_process", fake_run_process)
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )
    await sandbox.open()
    result = await sandbox.execute("sleep 100")

    assert result.timed_out
    assert not sandbox.is_open
    assert sandbox.defaults.working_directory == tmp_path.resolve()
    assert calls[0][1] == "run"
    name = calls[0][calls[0].index("--name") + 1]
    assert calls[1][1:3] == ("exec", "--workdir")
    assert calls[2] == ("docker", "rm", "--force", name)


@pytest.mark.asyncio
async def test_docker_reuses_one_container_for_multiple_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run_process(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> CommandResult:
        calls.append(argv)
        return CommandResult(str(kwargs["command"]), 0, "ok", "", 0.01)

    monkeypatch.setattr(docker_backend, "run_process", fake_run_process)
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path, environment={"BASE": "one"}),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )

    with pytest.raises(DockerSandboxStateError, match="not open"):
        await sandbox.execute("true")

    async with sandbox:
        name = sandbox.container_name
        assert name is not None
        assert sandbox.is_open
        first = await sandbox.execute("echo first")
        second = await sandbox.execute(
            "echo second",
            env={"EXTRA": "two"},
            stdin="input",
        )
        assert first.ok and second.ok

        with pytest.raises(DockerSandboxStateError, match="already open"):
            await sandbox.open()

    assert not sandbox.is_open
    assert sandbox.container_name is None
    assert [call[1] for call in calls] == ["run", "exec", "exec", "rm"]
    assert all(name in call for call in calls)
    assert "BASE=one" in calls[0]
    assert "EXTRA=two" in calls[2]
    assert "--interactive" in calls[2]


@pytest.mark.asyncio
async def test_docker_preserves_unavailable_error_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def unavailable(*_: object, **__: object) -> CommandResult:
        nonlocal calls
        calls += 1
        raise CommandUnavailableError("missing")

    monkeypatch.setattr(docker_backend, "run_process", unavailable)
    sandbox = DockerSandbox(
        "image",
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
    )
    with pytest.raises(CommandUnavailableError):
        await sandbox.open()
    assert calls == 1
    assert not sandbox.is_open


def test_bubblewrap_builds_policy_and_rejects_unsupported_limits(
    tmp_path: Path,
) -> None:
    policy = SandboxPolicy.for_workspace(
        tmp_path,
        enable_network_access=True,
    )
    sandbox = BubblewrapSandbox(
        defaults=CommandDefaults(tmp_path, environment={"NAME": "value"}),
        policy=policy,
    )
    argv = sandbox.build_argv("echo ok")
    assert "--unshare-all" in argv
    assert "--share-net" in argv
    assert "--bind" in argv
    assert "--clearenv" in argv
    assert "NAME" in argv
    assert argv[-1] == "echo ok"

    with pytest.raises(ValueError, match="command"):
        sandbox.build_argv("")
    limited = SandboxPolicy.for_workspace(
        tmp_path,
        limits=SandboxLimits(memory_bytes=1024),
    )
    with pytest.raises(ValueError, match="cannot enforce"):
        BubblewrapSandbox(
            defaults=CommandDefaults(tmp_path), policy=limited
        ).build_argv("true")


@pytest.mark.asyncio
async def test_bubblewrap_reports_unavailable_when_not_installed(
    tmp_path: Path,
) -> None:
    sandbox = BubblewrapSandbox(
        defaults=CommandDefaults(tmp_path),
        policy=SandboxPolicy.for_workspace(tmp_path),
        executable="definitely-not-bwrap",
    )
    assert not sandbox.available
    with pytest.raises(CommandUnavailableError, match="only available"):
        await sandbox.execute("true")
