import asyncio
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePath, PurePosixPath

from agenttoolkit.builtins.fs.errors import (
    EditError,
    FileTooLargeError,
    PathOutsideWorkspaceError,
)
from agenttoolkit.builtins.fs.models import Entry, GrepMatch


class LocalWorkspace:
    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        mounts: Mapping[str | PurePosixPath, str | os.PathLike[str]] | None = None,
        encoding: str = "utf-8",
        max_file_bytes: int | None = 10 * 1024 * 1024,
    ) -> None:
        if max_file_bytes is not None and max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive or None")

        root_path = Path(root).expanduser()
        if root_path.exists() and not root_path.is_dir():
            raise NotADirectoryError(root_path)
        root_path.mkdir(parents=True, exist_ok=True)

        self._root = root_path.resolve()
        self._mounts = _normalize_mounts(mounts)
        self._encoding = encoding
        self._max_file_bytes = max_file_bytes

    @property
    def root(self) -> Path:
        return self._root

    async def read_file(
        self,
        path: str | os.PathLike[str],
        *,
        encoding: str | None = None,
    ) -> str:
        return await asyncio.to_thread(self._read_file, path, encoding)

    def _read_file(
        self,
        path: str | os.PathLike[str],
        encoding: str | None,
    ) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        self._check_size(target.stat().st_size)
        return target.read_text(encoding=encoding or self._encoding)

    async def write_file(
        self,
        path: str | os.PathLike[str],
        content: str,
        *,
        encoding: str | None = None,
        create_parents: bool = True,
    ) -> None:
        await asyncio.to_thread(
            self._write_file,
            path,
            content,
            encoding,
            create_parents,
        )

    def _write_file(
        self,
        path: str | os.PathLike[str],
        content: str,
        encoding: str | None,
        create_parents: bool,
    ) -> None:
        target = self._resolve(path)
        if target.exists() and not target.is_file():
            raise IsADirectoryError(target)

        data = content.encode(encoding or self._encoding)
        self._check_size(len(data))
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        elif not target.parent.is_dir():
            raise FileNotFoundError(target.parent)

        self._assert_inside(target.parent.resolve(), self._base_of(target))
        _atomic_write(target, data)

    async def edit_file(
        self,
        path: str | os.PathLike[str],
        old: str,
        new: str,
        *,
        replace_all: bool = False,
        encoding: str | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._edit_file,
            path,
            old,
            new,
            replace_all,
            encoding,
        )

    def _edit_file(
        self,
        path: str | os.PathLike[str],
        old: str,
        new: str,
        replace_all: bool,
        encoding: str | None,
    ) -> int:
        if not old:
            raise EditError("old text must not be empty")

        selected_encoding = encoding or self._encoding
        content = self._read_file(path, selected_encoding)
        occurrences = content.count(old)
        if occurrences == 0:
            raise EditError("old text was not found")
        if occurrences > 1 and not replace_all:
            raise EditError(
                f"old text occurs {occurrences} times; use replace_all=True"
            )

        count = occurrences if replace_all else 1
        updated = content.replace(old, new, -1 if replace_all else 1)
        self._write_file(path, updated, selected_encoding, True)
        return count

    async def glob(self, pattern: str) -> Sequence[Entry]:
        return await asyncio.to_thread(self._glob, pattern)

    def _glob(self, pattern: str) -> list[Entry]:
        _validate_pattern(pattern)
        matches: list[Entry] = []
        for candidate in self._root.glob(pattern):
            try:
                matches.append(self._entry(candidate))
            except OSError:
                continue
        return sorted(matches, key=lambda entry: entry.path)

    async def grep(
        self,
        pattern: str,
        *,
        glob: str | None = None,
        case_sensitive: bool = True,
        context_lines: int = 0,
        max_matches: int | None = None,
    ) -> Sequence[GrepMatch]:
        return await asyncio.to_thread(
            self._grep,
            pattern,
            glob,
            case_sensitive,
            context_lines,
            max_matches,
        )

    def _grep(
        self,
        pattern: str,
        glob: str | None,
        case_sensitive: bool,
        context_lines: int,
        max_matches: int | None,
    ) -> list[GrepMatch]:
        if context_lines < 0:
            raise ValueError("context_lines must be non-negative")
        if max_matches is not None and max_matches < 0:
            raise ValueError("max_matches must be non-negative or None")
        try:
            regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error as error:
            raise ValueError(f"invalid regex pattern: {pattern}") from error

        candidates = (
            self._glob(glob) if glob is not None else self._list_dir(".", True, None)
        )
        matches: list[GrepMatch] = []
        for entry in candidates:
            if entry.is_dir:
                continue
            if max_matches is not None and len(matches) >= max_matches:
                break
            try:
                lines = (
                    self._resolve(entry.path)
                    .read_text(encoding=self._encoding)
                    .splitlines()
                )
            except (UnicodeDecodeError, OSError):
                continue
            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue
                matches.append(
                    GrepMatch(
                        path=entry.path,
                        line_number=index + 1,
                        line=line,
                        context_before=tuple(
                            lines[max(0, index - context_lines) : index]
                        ),
                        context_after=tuple(
                            lines[index + 1 : index + 1 + context_lines]
                        ),
                    )
                )
                if max_matches is not None and len(matches) >= max_matches:
                    break
        return matches

    async def list_dir(
        self,
        path: str | os.PathLike[str] = ".",
        *,
        recursive: bool = False,
        limit: int | None = None,
    ) -> Sequence[Entry]:
        return await asyncio.to_thread(self._list_dir, path, recursive, limit)

    def _list_dir(
        self,
        path: str | os.PathLike[str],
        recursive: bool,
        limit: int | None,
    ) -> list[Entry]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative or None")
        directory = self._resolve(path)
        if not directory.is_dir():
            raise NotADirectoryError(directory)

        discovered = directory.rglob("*") if recursive else directory.iterdir()
        candidates = sorted(discovered, key=self._display)
        entries: list[Entry] = []
        for candidate in candidates:
            if limit is not None and len(entries) >= limit:
                break
            try:
                entries.append(self._entry(candidate))
            except OSError:
                continue
        return sorted(entries, key=lambda entry: entry.path)

    async def stat(
        self,
        path: str | os.PathLike[str],
    ) -> Entry | None:
        return await asyncio.to_thread(self._stat, path)

    def _stat(self, path: str | os.PathLike[str]) -> Entry | None:
        target = self._resolve_entry(path)
        try:
            return self._entry(target)
        except FileNotFoundError:
            return None

    def _entry(self, path: Path) -> Entry:
        metadata = path.lstat()
        is_dir = path.is_dir()
        return Entry(
            path=self._display(path),
            is_dir=is_dir,
            is_symlink=path.is_symlink(),
            size=None if is_dir else metadata.st_size,
            modified=metadata.st_mtime,
        )

    def _resolve(self, path: str | os.PathLike[str]) -> Path:
        target, base = self._locate(path)
        target = target.resolve(strict=False)
        self._assert_inside(target, base)
        return target

    def _resolve_entry(self, path: str | os.PathLike[str]) -> Path:
        target, base = self._locate(path)
        target = Path(os.path.abspath(target))
        self._assert_inside(target, base)
        self._assert_inside(target.parent.resolve(strict=False), base)
        return target

    def _locate(self, path: str | os.PathLike[str]) -> tuple[Path, Path]:
        """Map a requested path to a host path plus the root it may not escape.

        Mount prefixes are matched textually because a POSIX-absolute prefix
        such as ``/skills`` is drive-relative on Windows, so ``Path`` would
        silently reinterpret it against the current drive.
        """
        text = os.fspath(path).replace("\\", "/")
        for prefix, mount in self._mounts:
            if text == prefix:
                return mount, mount
            if text.startswith(f"{prefix}/"):
                return mount / text[len(prefix) + 1 :], mount

        requested = Path(path)
        target = requested if requested.is_absolute() else self._root / requested
        return target, self._root

    def _assert_inside(self, path: Path, base: Path | None = None) -> None:
        base = self._root if base is None else base
        try:
            path.relative_to(base)
        except ValueError as error:
            raise PathOutsideWorkspaceError(
                f"path is outside workspace: {path}"
            ) from error

    def _base_of(self, path: Path) -> Path:
        for _, mount in self._mounts:
            if path == mount or mount in path.parents:
                return mount
        return self._root

    def _display(self, path: Path) -> str:
        base = self._base_of(path)
        relative = path.relative_to(base).as_posix()
        if base == self._root:
            return relative if relative != "." else "."
        prefix = next(prefix for prefix, mount in self._mounts if mount == base)
        return prefix if relative == "." else f"{prefix}/{relative}"

    def _check_size(self, size: int) -> None:
        if self._max_file_bytes is not None and size > self._max_file_bytes:
            raise FileTooLargeError(
                f"file is {size} bytes; limit is {self._max_file_bytes} bytes"
            )


def _normalize_mounts(
    mounts: Mapping[str | PurePosixPath, str | os.PathLike[str]] | None,
) -> tuple[tuple[str, Path], ...]:
    if not mounts:
        return ()

    normalized: list[tuple[str, Path]] = []
    for prefix, directory in mounts.items():
        text = str(prefix).replace("\\", "/").rstrip("/")
        if not text.startswith("/"):
            raise ValueError(f"mount prefix must be absolute: {prefix}")

        target = Path(directory).expanduser()
        if target.exists() and not target.is_dir():
            raise NotADirectoryError(target)
        target.mkdir(parents=True, exist_ok=True)
        normalized.append((text, target.resolve()))

    # Longest first so nested mounts win over their parent prefix.
    return tuple(sorted(normalized, key=lambda mount: len(mount[0]), reverse=True))


def _validate_pattern(pattern: str) -> None:
    if not pattern:
        raise ValueError("glob pattern must not be empty")
    parsed = PurePath(pattern)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise PathOutsideWorkspaceError(
            f"glob pattern must stay inside workspace: {pattern}"
        )


def _atomic_write(target: Path, data: bytes) -> None:
    existing_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            temporary.chmod(existing_mode)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
