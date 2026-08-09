from pathlib import Path

import pytest

from agenttoolkit.builtins.fs import (
    EditError,
    Entry,
    FileTooLargeError,
    GrepMatch,
    LocalWorkspace,
    PathOutsideWorkspaceError,
    Workspace,
)


@pytest.mark.asyncio
async def test_workspace_file_operations_and_exploration(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    assert isinstance(workspace, Workspace)

    await workspace.write_file("src/z.py", "first\n")
    await workspace.write_file("src/a.py", "alpha\n")
    assert await workspace.read_file("src/z.py") == "first\n"
    assert await workspace.edit_file("src/z.py", "first", "second") == 1
    assert await workspace.read_file("src/z.py") == "second\n"

    shallow = await workspace.list_dir()
    assert [(entry.path, entry.is_dir) for entry in shallow] == [("src", True)]
    recursive = await workspace.list_dir(recursive=True, limit=2)
    assert [entry.path for entry in recursive] == ["src", "src/a.py"]

    matches = await workspace.glob("**/*.py")
    assert [entry.path for entry in matches] == ["src/a.py", "src/z.py"]
    assert all(isinstance(entry, Entry) for entry in matches)
    assert matches[0].size == 6
    assert matches[0].modified is not None

    entry = await workspace.stat("src/a.py")
    assert entry is not None
    assert not entry.is_dir
    assert not entry.is_symlink
    assert await workspace.stat("missing") is None


@pytest.mark.asyncio
async def test_workspace_edit_is_deliberately_exact(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    await workspace.write_file("values.txt", "x x")

    with pytest.raises(EditError, match="occurs 2 times"):
        await workspace.edit_file("values.txt", "x", "y")
    assert await workspace.edit_file("values.txt", "x", "y", replace_all=True) == 2
    assert await workspace.read_file("values.txt") == "y y"

    with pytest.raises(EditError, match="must not be empty"):
        await workspace.edit_file("values.txt", "", "z")
    with pytest.raises(EditError, match="was not found"):
        await workspace.edit_file("values.txt", "absent", "z")


@pytest.mark.asyncio
async def test_workspace_rejects_escape_and_oversized_files(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path / "root", max_file_bytes=3)

    with pytest.raises(PathOutsideWorkspaceError):
        await workspace.write_file("../outside.txt", "x")
    with pytest.raises(PathOutsideWorkspaceError):
        await workspace.glob("../*")
    with pytest.raises(ValueError, match="must not be empty"):
        await workspace.glob("")
    with pytest.raises(FileTooLargeError):
        await workspace.write_file("large.txt", "four")

    (workspace.root / "large.txt").write_text("four")
    with pytest.raises(FileTooLargeError):
        await workspace.read_file("large.txt")
    with pytest.raises(FileNotFoundError):
        await workspace.write_file("missing/file.txt", "ok", create_parents=False)


@pytest.mark.asyncio
async def test_workspace_directory_and_symlink_metadata(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path / "root")
    await workspace.write_file("data/file.txt", "data")

    with pytest.raises(IsADirectoryError):
        await workspace.write_file("data", "no")
    with pytest.raises(NotADirectoryError):
        await workspace.list_dir("data/file.txt")
    with pytest.raises(ValueError, match="non-negative"):
        await workspace.list_dir(limit=-1)

    link = workspace.root / "link"
    try:
        link.symlink_to(workspace.root / "data", target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks is not permitted")

    entry = await workspace.stat("link")
    assert entry is not None
    assert entry.is_symlink
    assert entry.is_dir


@pytest.mark.asyncio
async def test_workspace_grep_finds_matches_with_context(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    await workspace.write_file("src/a.py", "one\nneedle\nthree\n")
    await workspace.write_file("src/b.py", "needle again\nunrelated\n")
    await workspace.write_file("notes.txt", "no match here\n")

    matches = await workspace.grep("needle")
    assert [(match.path, match.line_number) for match in matches] == [
        ("src/a.py", 2),
        ("src/b.py", 1),
    ]
    assert all(isinstance(match, GrepMatch) for match in matches)

    [with_context] = await workspace.grep("needle", glob="src/a.py", context_lines=1)
    assert with_context.context_before == ("one",)
    assert with_context.context_after == ("three",)


@pytest.mark.asyncio
async def test_workspace_grep_respects_glob_case_and_limit(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    await workspace.write_file("src/a.py", "Needle\nneedle\nneedle\n")
    await workspace.write_file("notes.txt", "needle\n")

    scoped = await workspace.grep("needle", glob="src/*.py")
    assert [match.path for match in scoped] == ["src/a.py", "src/a.py"]

    case_insensitive = await workspace.grep(
        "needle", glob="src/*.py", case_sensitive=False
    )
    assert len(case_insensitive) == 3

    limited = await workspace.grep("needle", glob="src/*.py", max_matches=1)
    assert len(limited) == 1


@pytest.mark.asyncio
async def test_workspace_grep_validates_input_and_skips_binaries(
    tmp_path: Path,
) -> None:
    workspace = LocalWorkspace(tmp_path)
    (workspace.root / "binary.dat").write_bytes(b"\xff\xfe\x00needle")
    await workspace.write_file("text.txt", "needle\n")

    matches = await workspace.grep("needle")
    assert [match.path for match in matches] == ["text.txt"]

    with pytest.raises(ValueError, match="invalid regex pattern"):
        await workspace.grep("(")
    with pytest.raises(ValueError, match="non-negative"):
        await workspace.grep("needle", context_lines=-1)
    with pytest.raises(ValueError, match="non-negative"):
        await workspace.grep("needle", max_matches=-1)


def test_workspace_constructor_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        LocalWorkspace(tmp_path, max_file_bytes=0)

    file_root = tmp_path / "file"
    file_root.write_text("content")
    with pytest.raises(NotADirectoryError):
        LocalWorkspace(file_root)


@pytest.mark.asyncio
async def test_workspace_mounts_expose_extra_roots(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    workspace = LocalWorkspace(tmp_path / "workspace", mounts={"/skills": skills})

    await workspace.write_file("/skills/openhue-cli/SKILL.md", "hello world")
    assert (skills / "openhue-cli" / "SKILL.md").read_text() == "hello world"
    assert await workspace.read_file("/skills/openhue-cli/SKILL.md") == "hello world"
    assert (
        await workspace.edit_file("/skills/openhue-cli/SKILL.md", "world", "agent") == 1
    )

    entry = await workspace.stat("/skills/openhue-cli/SKILL.md")
    assert entry is not None
    assert entry.path == "/skills/openhue-cli/SKILL.md"
    assert [
        item.path for item in await workspace.list_dir("/skills", recursive=True)
    ] == [
        "/skills/openhue-cli",
        "/skills/openhue-cli/SKILL.md",
    ]


@pytest.mark.asyncio
async def test_workspace_mounts_still_reject_escaping_paths(tmp_path: Path) -> None:
    workspace = LocalWorkspace(
        tmp_path / "workspace", mounts={"/skills": tmp_path / "skills"}
    )

    with pytest.raises(PathOutsideWorkspaceError):
        await workspace.write_file("/skills/../escape.txt", "no")
    with pytest.raises(PathOutsideWorkspaceError):
        await workspace.read_file("/other/file.txt")


def test_workspace_mount_prefix_must_be_absolute(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        LocalWorkspace(tmp_path / "workspace", mounts={"skills": tmp_path / "skills"})
