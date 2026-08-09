from pathlib import Path

import pytest

from agenttoolkit.builtins.fs import LocalWorkspace
from agenttoolkit.tools import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    ToolContext,
    Tools,
)
from experiments.tools import register_file_tools


@pytest.mark.asyncio
async def test_file_tools_read_write_and_edit_workspace_files(
    tmp_path: Path,
) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = Tools(context=ToolContext(workspace))
    register_file_tools(tools)

    written = await tools.execute(
        "write_file",
        {"path": "notes/message.txt", "content": "hello world"},
    )
    read = await tools.execute("read_file", {"path": "notes/message.txt"})
    edited = await tools.execute(
        "edit_file",
        {
            "path": "notes/message.txt",
            "old": "world",
            "new": "agent",
        },
    )

    assert written == "Wrote notes/message.txt"
    assert read == "hello world"
    assert edited == "Replaced 1 occurrence(s) in notes/message.txt"
    assert await workspace.read_file("notes/message.txt") == "hello agent"


@pytest.mark.asyncio
async def test_file_tools_return_actionable_workspace_errors(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = Tools(
        context=ToolContext(workspace),
        middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()),
    )
    register_file_tools(tools)

    missing = await tools.execute("read_file", {"path": "missing.txt"})
    outside = await tools.execute(
        "write_file",
        {"path": "../outside.txt", "content": "no"},
    )

    assert isinstance(missing, str)
    assert "missing.txt" in missing
    assert isinstance(outside, str)
    assert "outside workspace" in outside


def test_file_tools_are_registered_in_expected_order() -> None:
    tools = Tools()
    register_file_tools(tools)

    assert [tool.name for tool in tools] == ["read_file", "write_file", "edit_file"]
