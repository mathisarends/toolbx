import asyncio
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Literal, Self

from agenttoolkit.builtins.shell.command import (
    CommandError,
    CommandResult,
    CommandUnavailableError,
    run_process,
)
from agenttoolkit.builtins.shell.execution import (
    DEFAULT_TIMEOUT,
    CommandDefaults,
    CommandTimeout,
    resolve_timeout,
)
from agenttoolkit.builtins.shell.policy import SandboxPolicy

type DockerNetworkMode = Literal["bridge", "host"]


@dataclass(frozen=True, slots=True)
class BindMount:
    source: Path
    target: PurePosixPath
    writable: bool = False

    def __post_init__(self) -> None:
        if (
            not self.target.is_absolute()
            or self.target == PurePosixPath("/")
            or ".." in self.target.parts
        ):
            raise ValueError(
                "mount target must be an absolute container path below '/': "
                f"{str(self.target)!r}"
            )

    @classmethod
    def read_only(
        cls,
        source: str | os.PathLike[str],
        target: str | PurePosixPath,
    ) -> Self:
        return cls(_resolve_source(source), PurePosixPath(target))

    @classmethod
    def read_write(
        cls,
        source: str | os.PathLike[str],
        target: str | PurePosixPath,
    ) -> Self:
        return cls(_resolve_source(source), PurePosixPath(target), writable=True)


def _resolve_source(source: str | os.PathLike[str]) -> Path:
    return Path(source).expanduser().resolve(strict=False)


_KEEP_ALIVE_COMMAND = "while :; do sleep 3600; done"


class DockerSandboxStateError(CommandError):
    pass


class DockerSandbox:
    def __init__(
        self,
        image: str,
        *,
        defaults: CommandDefaults | None = None,
        policy: SandboxPolicy | None = None,
        mounts: Sequence[BindMount] = (),
        inherit_environment: Sequence[str] = (),
        user: str | None = None,
        network_mode: DockerNetworkMode | None = None,
        executable: str = "docker",
        shell: str = "/bin/sh",
        shell_arguments: Sequence[str] = ("-lc",),
    ) -> None:
        if not image.strip():
            raise ValueError("image must not be empty")
        self._image = image
        self._defaults = defaults or CommandDefaults()
        self._policy = policy or SandboxPolicy()
        self._mount_definitions = _validate_mounts(mounts)
        self._inherit_environment = _validate_environment_names(inherit_environment)
        if user is not None and not user.strip():
            raise ValueError("user must not be empty")
        self._user = user
        if network_mode is not None:
            if network_mode not in ("bridge", "host"):
                raise ValueError("network mode must be 'bridge' or 'host'")
            if not self._policy.enable_network_access:
                raise ValueError(
                    "network mode requires network access to be enabled by policy"
                )
        self._network_mode = network_mode
        self._executable = executable
        self._shell = shell
        self._shell_arguments = tuple(shell_arguments)
        self._container_name: str | None = None
        self._active_mounts: tuple[tuple[Path, PurePosixPath, bool], ...] | None = None
        self._operation_lock = asyncio.Lock()
        self._active_commands = 0
        self._commands_idle = asyncio.Event()
        self._commands_idle.set()
        self._is_open = False

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    @property
    def defaults(self) -> CommandDefaults:
        return self._defaults

    @property
    def mounts(self) -> tuple[BindMount, ...]:
        return self._mount_definitions

    @property
    def inherit_environment(self) -> tuple[str, ...]:
        return self._inherit_environment

    @property
    def user(self) -> str | None:
        return self._user

    @property
    def network_mode(self) -> DockerNetworkMode | None:
        return self._network_mode

    @property
    def container_name(self) -> str | None:
        return self._container_name

    @property
    def is_open(self) -> bool:
        return self._is_open

    async def open(self) -> None:
        async with self._operation_lock:
            if self._is_open:
                raise DockerSandboxStateError("sandbox is already open")

            container_name = f"agenttoolkit-{uuid.uuid4().hex}"
            selected_cwd = self._select_working_directory(None)
            mounts = self._mounts(selected_cwd)
            argv = self._build_open_argv(container_name, selected_cwd, mounts)
            try:
                result = await run_process(
                    argv,
                    command=f"open Docker sandbox {container_name}",
                    cwd=None,
                    env=None,
                    stdin=None,
                    timeout=self._defaults.limits.timeout_seconds,
                    max_output_bytes=self._defaults.limits.max_output_bytes,
                )
            except CommandUnavailableError:
                raise
            except asyncio.CancelledError:
                await asyncio.shield(self._remove_container(container_name))
                raise
            except BaseException:
                await self._remove_container(container_name)
                raise

            if not result.ok:
                await self._remove_container(container_name)
                result.check_returncode()

            self._container_name = container_name
            self._active_mounts = mounts
            self._is_open = True

    async def close(self) -> None:
        async with self._operation_lock:
            container_name = self._container_name
            if container_name is None:
                self._clear_container_state()
                return
            await self._commands_idle.wait()
            try:
                await self._remove_container(container_name)
            except asyncio.CancelledError:
                await asyncio.shield(self._remove_container(container_name))
                raise
            finally:
                self._clear_container_state()

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: CommandTimeout = DEFAULT_TIMEOUT,
    ) -> CommandResult:
        if not command:
            raise ValueError("command must not be empty")

        async with self._operation_lock:
            container_name, mounts = self._active_container()
            argv = self._build_exec_argv(
                command,
                container_name,
                mounts,
                cwd=cwd,
                env=env,
                interactive=stdin is not None,
            )
            self._active_commands += 1
            self._commands_idle.clear()
        try:
            try:
                result = await run_process(
                    argv,
                    command=command,
                    cwd=None,
                    env=None,
                    stdin=stdin,
                    timeout=resolve_timeout(
                        timeout,
                        self._defaults.limits.timeout_seconds,
                    ),
                    max_output_bytes=self._defaults.limits.max_output_bytes,
                    spill_directory=self._defaults.spill_directory,
                )
            except CommandUnavailableError:
                raise
            except asyncio.CancelledError:
                await asyncio.shield(self._discard_container(container_name))
                raise
            except BaseException:
                await self._discard_container(container_name)
                raise
            if result.timed_out:
                await self._discard_container(container_name)
            return result
        finally:
            self._active_commands -= 1
            if self._active_commands == 0:
                self._commands_idle.set()

    def build_open_argv(
        self,
        *,
        container_name: str | None = None,
    ) -> tuple[str, ...]:
        selected_cwd = self._select_working_directory(None)
        mounts = self._mounts(selected_cwd)
        name = container_name or f"agenttoolkit-{uuid.uuid4().hex}"
        return self._build_open_argv(name, selected_cwd, mounts)

    def build_exec_argv(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        interactive: bool = False,
    ) -> tuple[str, ...]:
        if not command:
            raise ValueError("command must not be empty")
        container_name, mounts = self._active_container()
        return self._build_exec_argv(
            command,
            container_name,
            mounts,
            cwd=cwd,
            env=env,
            interactive=interactive,
        )

    def _build_open_argv(
        self,
        container_name: str,
        selected_cwd: Path,
        mounts: tuple[tuple[Path, PurePosixPath, bool], ...],
    ) -> tuple[str, ...]:
        if not container_name:
            raise ValueError("container name must not be empty")
        container_cwd = _container_path(selected_cwd, mounts)

        argv = [
            self._executable,
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--init",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev",
            "--workdir",
            str(container_cwd),
        ]
        if self._network_mode is not None:
            argv.extend(("--network", self._network_mode))
        elif not self._policy.enable_network_access:
            argv.extend(("--network", "none"))
        if selected_user := _resolve_user(self._user):
            argv.extend(("--user", selected_user))

        limits = self._policy.limits
        if limits.memory_bytes is not None:
            argv.extend(("--memory", str(limits.memory_bytes)))
        if limits.pids is not None:
            argv.extend(("--pids-limit", str(limits.pids)))
        if limits.cpus is not None:
            argv.extend(("--cpus", str(limits.cpus)))

        for source, target, writable in mounts:
            specification = f"type=bind,src={source},dst={target}"
            if not writable:
                specification += ",readonly"
            argv.extend(("--mount", specification))

        for key in self._inherit_environment:
            if key in self._defaults.environment:
                continue
            if key not in os.environ:
                raise ValueError(f"host environment variable is not set: {key}")
            argv.extend(("--env", key))
        for key, value in self._defaults.environment.items():
            argv.extend(("--env", f"{key}={value}"))

        argv.extend((self._image, self._shell, "-c", _KEEP_ALIVE_COMMAND))
        return tuple(argv)

    def _build_exec_argv(
        self,
        command: str,
        container_name: str,
        mounts: tuple[tuple[Path, PurePosixPath, bool], ...],
        *,
        cwd: str | os.PathLike[str] | None,
        env: Mapping[str, str] | None,
        interactive: bool,
    ) -> tuple[str, ...]:
        if not command:
            raise ValueError("command must not be empty")
        selected_cwd = self._select_working_directory(cwd)
        container_cwd = _container_path(selected_cwd, mounts)
        argv = [self._executable, "exec"]
        if interactive:
            argv.append("--interactive")
        argv.extend(("--workdir", str(container_cwd)))
        for key, value in (env or {}).items():
            if not key or "=" in key or "\x00" in key:
                raise ValueError(f"invalid environment variable name: {key!r}")
            if "\x00" in value:
                raise ValueError(f"environment value for {key!r} contains NUL")
            argv.extend(("--env", f"{key}={value}"))
        argv.extend((container_name, self._shell, *self._shell_arguments, command))
        return tuple(argv)

    def container_path(
        self,
        path: str | os.PathLike[str],
    ) -> PurePosixPath:
        working_directory = self._select_working_directory(None)
        requested = Path(path).expanduser()
        if not requested.is_absolute():
            requested = working_directory / requested
        requested = requested.resolve(strict=False)
        mounts = self._active_mounts or self._mounts(working_directory)
        return _container_path(requested, mounts)

    async def _discard_container(self, name: str) -> None:
        try:
            await self._remove_container(name)
        finally:
            if self._container_name == name:
                self._clear_container_state()

    def _clear_container_state(self) -> None:
        self._container_name = None
        self._active_mounts = None
        self._is_open = False

    def _active_container(
        self,
    ) -> tuple[str, tuple[tuple[Path, PurePosixPath, bool], ...]]:
        self._require_open()
        if self._container_name is None or self._active_mounts is None:
            raise DockerSandboxStateError("sandbox container state is inconsistent")
        return self._container_name, self._active_mounts

    def _require_open(self) -> None:
        if not self._is_open:
            raise DockerSandboxStateError(
                "sandbox is not open; call open() or use 'async with' first"
            )

    def _select_working_directory(
        self,
        path: str | os.PathLike[str] | None,
    ) -> Path:
        selected = self._defaults.select_working_directory(path)
        self._policy.require_readable(selected)
        return selected

    async def _remove_container(self, name: str) -> None:
        try:
            await run_process(
                (self._executable, "rm", "--force", name),
                command=f"remove container {name}",
                cwd=None,
                env=None,
                stdin=None,
                timeout=10,
                max_output_bytes=64 * 1024,
            )
        except CommandError:
            pass

    def _mounts(
        self,
        working_directory: Path,
    ) -> tuple[tuple[Path, PurePosixPath, bool], ...]:
        roots: list[tuple[Path, bool]] = []
        workspace = self._defaults.working_directory or working_directory
        roots.append((workspace, self._policy.allows_write(workspace)))
        roots.extend((path, False) for path in self._policy.readable_paths)
        roots.extend((path, True) for path in self._policy.writable_paths)

        merged: dict[Path, bool] = {}
        for source, writable in roots:
            if not source.exists():
                raise FileNotFoundError(source)
            merged[source] = merged.get(source, False) or writable

        explicit_sources = {mount.source for mount in self._mount_definitions}
        mounts: list[tuple[Path, PurePosixPath, bool]] = []
        extra_index = 0
        for source, writable in merged.items():
            if source in explicit_sources:
                continue
            if source == workspace:
                target = PurePosixPath("/workspace")
            else:
                target = PurePosixPath("/mnt") / f"path-{extra_index}"
                extra_index += 1
            mounts.append((source, target, writable))
        mounts.extend(
            (mount.source, mount.target, mount.writable)
            for mount in self._mount_definitions
        )

        targets: dict[PurePosixPath, Path] = {}
        for source, target, _ in mounts:
            if not source.exists():
                raise FileNotFoundError(source)
            if existing := targets.get(target):
                raise ValueError(
                    f"mount target {target} is used by both {existing} and {source}"
                )
            targets[target] = source
        mounts.sort(key=lambda mount: len(mount[1].parts))
        return tuple(mounts)


def _validate_mounts(mounts: Sequence[BindMount]) -> tuple[BindMount, ...]:
    normalized = tuple(mounts)
    sources: set[Path] = set()
    targets: set[PurePosixPath] = set()
    for mount in normalized:
        if mount.source in sources:
            raise ValueError(
                f"mount source is configured more than once: {mount.source}"
            )
        if mount.target in targets:
            raise ValueError(
                f"mount target is configured more than once: {mount.target}"
            )
        sources.add(mount.source)
        targets.add(mount.target)
    return normalized


def _validate_environment_names(names: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for name in names:
        if not name or "=" in name or "\x00" in name:
            raise ValueError(f"invalid environment variable name: {name!r}")
        if name not in normalized:
            normalized.append(name)
    return tuple(normalized)


def _resolve_user(user: str | None) -> str | None:
    if user != "host":
        return user
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return None
    return f"{getuid()}:{getgid()}"


def _container_path(
    path: Path,
    mounts: tuple[tuple[Path, PurePosixPath, bool], ...],
) -> PurePosixPath:
    candidates: list[tuple[int, PurePosixPath]] = []
    for source, target, _ in mounts:
        try:
            relative = path.relative_to(source)
        except ValueError:
            continue
        candidates.append((len(source.parts), target.joinpath(*relative.parts)))
    if not candidates:
        raise PermissionError(f"path is not mounted in container: {path}")
    return max(candidates, key=lambda candidate: candidate[0])[1]
