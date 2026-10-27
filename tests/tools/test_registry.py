import logging

import pytest

from toolbx import Toolbox, ToolCall, ToolHandler, Toolset, tool


class FileTools(Toolset, namespace=None):
    def __init__(self) -> None:
        self.writable = True

    @tool("Read a file", tags=["read"])
    def read(self) -> str:
        return "content"

    @tool("Write a file", tags=["write"], available_when=lambda self: self.writable)
    def write(self) -> str:
        return "written"

    @tool("Delete a file", tags=["write", "danger"])
    def delete(self) -> str:
        return "deleted"


def test_registry_supports_lookup_membership_names_and_removal() -> None:
    toolbox = Toolbox(FileTools())

    assert toolbox.names() == ("read", "write", "delete")
    assert "read" in toolbox
    assert "missing" not in toolbox
    assert toolbox["read"].description == "Read a file"
    with pytest.raises(KeyError, match="Unknown tool 'missing'"):
        toolbox["missing"]

    removed = toolbox.remove("delete")
    assert removed.name == "delete"
    assert "delete" not in toolbox
    with pytest.raises(KeyError, match="Unknown tool 'delete'"):
        toolbox.remove("delete")


@pytest.mark.asyncio
async def test_subset_selects_by_name_or_tag_and_keeps_middleware() -> None:
    seen: list[str] = []

    async def record(call: ToolCall, call_next: ToolHandler) -> object:
        seen.append(call.name)
        return await call_next(call)

    tools = FileTools()
    toolbox = Toolbox(tools, middleware=[record])

    readers = toolbox.subset(tags=["read"])
    assert readers.names() == ("read",)
    assert toolbox.subset(names=["read"], tags=["danger"]).names() == (
        "read",
        "delete",
    )
    assert await readers.execute("read") == "content"
    assert seen == ["read"]

    readers.remove("read")
    assert "read" in toolbox
    assert toolbox.subset(names=["write"])["write"] is toolbox["write"]


def test_subset_rejects_unknown_names_and_missing_selection() -> None:
    toolbox = Toolbox(FileTools())

    with pytest.raises(ValueError, match="Unknown tools: missing"):
        toolbox.subset(names=["missing"])
    with pytest.raises(ValueError, match="needs names or tags"):
        toolbox.subset()
    with pytest.raises(TypeError, match="collections"):
        toolbox.subset(tags="read")


@pytest.mark.asyncio
async def test_unavailable_tool_logs_the_real_reason_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tools = FileTools()
    tools.writable = False
    toolbox = Toolbox(tools)

    with (
        caplog.at_level(logging.DEBUG, logger="toolbx.tools.toolbox"),
        pytest.raises(LookupError, match="Unknown tool 'write'"),
    ):
        await toolbox.execute("write")
    assert "registered but currently unavailable" in caplog.text
