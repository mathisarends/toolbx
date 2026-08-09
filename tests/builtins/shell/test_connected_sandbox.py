from pathlib import Path

import pytest

from agenttoolkit.builtins.shell import BindMount, CommandRunner, LocalShellRunner
from experiments.sandboxing import connected_sandbox, workspace_runner

_CONNECTED_ENVIRONMENT = (
    "HUE_BRIDGE_IP",
    "HUE_APP_KEY",
    "SONOS_IP_ADDRESS",
    "SONOS_SPEAKER_NAME",
)


@pytest.mark.asyncio
async def test_workspace_runner_exposes_local_runner_without_fake_lifecycle(
    tmp_path: Path,
) -> None:
    async with workspace_runner(tmp_path, unsafe=True) as runner:
        assert isinstance(runner, CommandRunner)
        assert isinstance(runner, LocalShellRunner)
        assert not hasattr(runner, "open")
        result = await runner.execute("echo ok")

    assert result.ok


@pytest.mark.parametrize("missing_name", _CONNECTED_ENVIRONMENT)
def test_connected_sandbox_rejects_missing_forwarded_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    monkeypatch.setenv("SPOGO_CONFIG_DIR", str(tmp_path / "spogo"))
    for name in _CONNECTED_ENVIRONMENT:
        monkeypatch.setenv(name, "configured")
    monkeypatch.delenv(missing_name)

    sandbox = connected_sandbox(tmp_path)

    with pytest.raises(
        ValueError,
        match=f"host environment variable is not set: {missing_name}",
    ):
        sandbox.build_open_argv()


def test_connected_sandbox_uses_host_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOGO_CONFIG_DIR", str(tmp_path / "spogo"))
    for name in _CONNECTED_ENVIRONMENT:
        monkeypatch.setenv(name, "configured")

    argv = connected_sandbox(tmp_path).build_open_argv(container_name="test-sandbox")

    assert ("--network", "host") == argv[
        argv.index("--network") : argv.index("--network") + 2
    ]


def test_connected_sandbox_accepts_writable_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOGO_CONFIG_DIR", str(tmp_path / "spogo"))
    for name in _CONNECTED_ENVIRONMENT:
        monkeypatch.setenv(name, "configured")
    skills = tmp_path / "skills"
    skills.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    sandbox = connected_sandbox(
        workspace,
        mounts=(BindMount.read_write(skills, "/skills"),),
    )

    assert sandbox.mounts == (BindMount.read_write(skills, "/skills"),)
    argv = sandbox.build_open_argv(container_name="test-sandbox")
    specification = next(
        argv[index + 1]
        for index, argument in enumerate(argv)
        if argument == "--mount" and "dst=/skills" in argv[index + 1]
    )
    assert "readonly" not in specification
