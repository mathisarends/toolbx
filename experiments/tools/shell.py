from pydantic import BaseModel, Field

from agenttoolkit import OutputBudget
from agenttoolkit.builtins.shell import CommandResult, CommandRunner
from agenttoolkit.tools import Inject, ToolRegistry


class ShellParams(BaseModel):
    command: str = Field(description="Shell command to run in the sandbox")


def register_shell_tool(
    tools: ToolRegistry,
    *,
    name: str = "bash",
    description: str = "Run a Bash command in the sandbox.",
    requires_approval: bool = False,
    budget: OutputBudget | None = None,
) -> None:
    output_budget = budget or OutputBudget()

    @tools.action(
        description,
        name=name,
        params=ShellParams,
        status=lambda params: f"Running: {params.command}",
        requires_approval=requires_approval,
    )
    async def run_shell(
        params: ShellParams,
        runner: Inject[CommandRunner],
    ) -> str:
        result = await runner.execute(params.command)
        output = output_budget.shape(result.output, hint=_spill_hint(result))
        if not result.ok:
            raise RuntimeError(
                f"exit={result.returncode} timed_out={result.timed_out}\n{output}"
            )
        return output


def _spill_hint(result: CommandResult) -> str | None:
    paths = result.spill_paths
    if not paths:
        return None
    return f"full output: {', '.join(str(path) for path in paths)}"
