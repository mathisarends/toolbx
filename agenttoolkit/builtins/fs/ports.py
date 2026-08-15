import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from agenttoolkit.builtins.fs.models import Entry, GrepMatch


@runtime_checkable
class Workspace(Protocol):
    @property
    def root(self) -> Path: ...

    async def read_file(
        self,
        path: str | os.PathLike[str],
        *,
        encoding: str | None = None,
    ) -> str: ...

    async def write_file(
        self,
        path: str | os.PathLike[str],
        content: str,
        *,
        encoding: str | None = None,
        create_parents: bool = True,
    ) -> None: ...

    async def edit_file(
        self,
        path: str | os.PathLike[str],
        old: str,
        new: str,
        *,
        replace_all: bool = False,
        encoding: str | None = None,
    ) -> int: ...

    async def glob(self, pattern: str) -> Sequence[Entry]: ...

    async def grep(
        self,
        pattern: str,
        *,
        glob: str | None = None,
        case_sensitive: bool = True,
        context_lines: int = 0,
        max_matches: int | None = None,
    ) -> Sequence[GrepMatch]: ...

    async def list_dir(
        self,
        path: str | os.PathLike[str] = ".",
        *,
        recursive: bool = False,
        limit: int | None = None,
    ) -> Sequence[Entry]: ...

    async def stat(
        self,
        path: str | os.PathLike[str],
    ) -> Entry | None: ...
