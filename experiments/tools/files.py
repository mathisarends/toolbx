from pydantic import BaseModel, Field

from agenttoolkit.builtins.fs import Workspace
from agenttoolkit.tools import Inject, ToolRegistry


class ReadFileParams(BaseModel):
    path: str = Field(description="File path relative to the workspace")


class WriteFileParams(BaseModel):
    path: str = Field(description="File path relative to the workspace")
    content: str = Field(description="Complete UTF-8 file content")


class EditFileParams(BaseModel):
    path: str = Field(description="File path relative to the workspace")
    old: str = Field(description="Exact text to replace")
    new: str = Field(description="Replacement text")
    replace_all: bool = Field(
        default=False,
        description="Replace every occurrence instead of requiring exactly one",
    )


def register_file_tools(tools: ToolRegistry) -> None:
    @tools.tool(
        "Read a UTF-8 text file from the workspace.",
        status=lambda params: f"Reading {params.path}",
    )
    async def read_file(
        params: ReadFileParams,
        workspace: Inject[Workspace],
    ) -> str:
        return await workspace.read_file(params.path)

    @tools.tool(
        "Write the complete UTF-8 content of a file in the workspace. "
        "Missing parent directories are created.",
        status=lambda params: f"Writing {params.path}",
    )
    async def write_file(
        params: WriteFileParams,
        workspace: Inject[Workspace],
    ) -> str:
        await workspace.write_file(params.path, params.content)
        return f"Wrote {params.path}"

    @tools.tool(
        "Replace exact text in a UTF-8 file in the workspace. By default the "
        "old text must occur exactly once.",
        status=lambda params: f"Editing {params.path}",
    )
    async def edit_file(
        params: EditFileParams,
        workspace: Inject[Workspace],
    ) -> str:
        replacements = await workspace.edit_file(
            params.path,
            params.old,
            params.new,
            replace_all=params.replace_all,
        )
        return f"Replaced {replacements} occurrence(s) in {params.path}"
