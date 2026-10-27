import asyncio
import sys
from typing import Any

from llmify import RetryableError, RetryEvent

from agenttoolkit.tools import ToolContext, ToolRegistry
from experiments.agent import Agent

# Second line of defence behind llmify's own retries: those cover a burst of a
# few seconds, these cover an outage that lasts minutes.
_RESUME_DELAYS = (15.0, 45.0, 120.0)


class Console:
    """Shared terminal UI for the interactive experiments."""

    def __init__(
        self,
        toolbox: ToolRegistry,
        *,
        context: ToolContext | None = None,
    ) -> None:
        self._toolbox = toolbox
        self._context = context

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        print(f"  -> {name}({arguments})")

    def on_tool_result(
        self,
        name: str,
        result: object,
    ) -> None:
        print(f"  <- {name}:\n{result}")

    def on_retry(self, event: RetryEvent) -> None:
        print(
            f"  .. retry {event.retry_number}/{event.max_retries} "
            f"in {event.delay:.1f}s: {event.error}"
        )

    def confirm(self, name: str, arguments: dict[str, Any]) -> bool:
        answer = input(f"  ?? approve '{name}({arguments})'? [y/N] ")
        return answer.strip().lower() == "y"

    def print_tools(self) -> None:
        print("Registered tools (available in current context):")
        for tool in self._toolbox:
            if not tool.is_available(self._context):
                continue
            flags = []
            if tool.requires_approval:
                flags.append("requires_approval")
            if tool.available_when is not None:
                flags.append("gated")
            flag_text = f" [{', '.join(flags)}]" if flags else ""
            print(
                f"  - {tool.name}: "
                f"{tool.resolve_description(self._context)}{flag_text}"
            )
        print()

    async def run(
        self,
        agent: Agent,
        banner: str,
        *,
        prompt: str | None = None,
    ) -> None:
        _configure_stdout()
        if prompt:
            await self._turn(agent, prompt)
            return

        print(banner)
        while True:
            user_input = input("you> ").strip()
            if user_input in ("exit", "quit"):
                return
            if not user_input:
                continue
            await self._turn(agent, user_input)

    async def _turn(self, agent: Agent, user_input: str) -> None:
        answer = await self._answer(agent, user_input)
        if answer is not None:
            print(f"agent> {answer}")

    async def _answer(self, agent: Agent, user_input: str) -> str | None:
        try:
            return await agent.run(user_input)
        except RetryableError as error:
            last_error = error

        # The user message is already in the history, so the later attempts
        # resume that turn instead of sending it a second time.
        for delay in _RESUME_DELAYS:
            print(f"  .. provider unavailable ({last_error}); resuming in {delay:.0f}s")
            await asyncio.sleep(delay)
            try:
                return await agent.resume()
            except RetryableError as error:
                last_error = error

        print(f"  !! provider still unavailable: {last_error}")
        print("  !! turn aborted - send a message to try again.")
        return None


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
