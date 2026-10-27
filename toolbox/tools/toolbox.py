from typing import Any

from toolbox.tools.context import ToolContext
from toolbox.tools.registry import ToolRegistry
from toolbox.tools.schema import ToolSchema


class Toolbox(ToolRegistry):
    """Tools exposed through provider tool-call schemas."""

    def schemas(self, *, context: ToolContext | None = None) -> list[ToolSchema]:
        active_context = self._context if context is None else context
        return [
            tool.to_schema(active_context)
            for tool in self._tools.values()
            if tool.is_available(active_context)
        ]

    def to_openai(self, *, context: ToolContext | None = None) -> list[dict[str, Any]]:
        return [schema.to_openai_schema() for schema in self.schemas(context=context)]

    def to_anthropic(
        self, *, context: ToolContext | None = None
    ) -> list[dict[str, Any]]:
        return [
            schema.to_anthropic_schema() for schema in self.schemas(context=context)
        ]
