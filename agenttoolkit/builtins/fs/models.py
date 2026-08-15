from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Entry:
    path: str
    is_dir: bool
    is_symlink: bool
    size: int | None = None
    modified: float | None = None


@dataclass(frozen=True, slots=True)
class GrepMatch:
    path: str
    line_number: int
    line: str
    context_before: tuple[str, ...] = ()
    context_after: tuple[str, ...] = ()
