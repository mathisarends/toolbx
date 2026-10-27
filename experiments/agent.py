import json
from collections.abc import Callable
from typing import Any

from llmify import (
    AssistantMessage,
    ChatModel,
    Message,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from pydantic import BaseModel

from agenttoolkit.tools import Toolbox, ToolSchemaFormat


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


OnToolCall = Callable[[str, dict[str, Any]], None]
OnToolResult = Callable[[str, object], None]


class Agent:
    def __init__(
        self,
        model: ChatModel,
        toolbox: Toolbox,
        *,
        system_prompt: str | Callable[[], str] | None = None,
        on_tool_call: OnToolCall | None = None,
        on_tool_result: OnToolResult | None = None,
        confirm: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self._model = model
        self._toolbox = toolbox
        self._messages: list[Message] = []
        self._on_tool_call = on_tool_call
        self._on_tool_result = on_tool_result
        self._confirm = confirm
        self._system_prompt: Callable[[], str] | None
        if isinstance(system_prompt, str):
            self._system_prompt = None
            self._messages.append(SystemMessage(content=system_prompt))
        else:
            self._system_prompt = system_prompt

    async def run(self, user_input: str) -> str:
        self._messages.append(UserMessage(content=user_input))
        return await self._loop()

    async def resume(self) -> str:
        """Continue after a failed turn without re-appending the user message.

        Every point where `_loop` can raise leaves the history in a state the
        provider accepts again (ending in a user message or in tool results),
        so a transient provider error can be retried from here instead of
        discarding the conversation.
        """
        return await self._loop()

    async def _loop(self) -> str:
        while True:
            schema = self._toolbox.get_schema(ToolSchemaFormat.OPENAI)
            messages = (
                [
                    SystemMessage(content=self._system_prompt()),
                    *self._messages,
                ]
                if self._system_prompt is not None
                else self._messages
            )
            completion = await self._model.invoke(messages, tools=schema)

            self._messages.append(
                AssistantMessage(
                    content=completion.completion or None,
                    tool_calls=completion.tool_calls,
                )
            )

            if not completion.tool_calls:
                return completion.completion

            for call in completion.tool_calls:
                arguments = json.loads(call.function.arguments or "{}")
                if self._on_tool_call:
                    self._on_tool_call(call.function.name, arguments)

                tool = self._toolbox.get(call.function.name)
                if (
                    tool is not None
                    and tool.requires_approval
                    and self._confirm is not None
                    and not self._confirm(call.function.name, arguments)
                ):
                    result = "Tool failed: Declined by user"
                else:
                    result = await self._toolbox.execute(call.function.name, arguments)

                if self._on_tool_result:
                    self._on_tool_result(call.function.name, result)

                self._messages.append(
                    ToolResultMessage(
                        tool_call_id=call.id,
                        content=json.dumps(result, default=_json_default),
                    )
                )
