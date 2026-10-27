from typing import Any, overload

from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.models import ToolSchemaFormat
from agenttoolkit.tools.registry import ToolRegistry
from agenttoolkit.tools.schema import ToolSchema


class Toolbox(ToolRegistry):
    """Tools exposed through provider tool-call schemas."""

    @overload
    def get_schema(
        self,
        schema_format: ToolSchemaFormat = ToolSchemaFormat.NATIVE,
        *,
        context: ToolContext | None = None,
    ) -> list[ToolSchema]: ...

    @overload
    def get_schema(
        self,
        schema_format: str,
        *,
        context: ToolContext | None = None,
    ) -> list[ToolSchema] | list[dict[str, Any]]: ...

    def get_schema(
        self,
        schema_format: ToolSchemaFormat | str = ToolSchemaFormat.NATIVE,
        *,
        context: ToolContext | None = None,
    ) -> list[ToolSchema] | list[dict[str, Any]]:
        active_context = self._context if context is None else context
        schemas = [
            tool.to_schema(active_context)
            for tool in self._tools.values()
            if tool.is_available(active_context)
        ]
        schema_format = ToolSchemaFormat(schema_format)
        if schema_format is ToolSchemaFormat.OPENAI:
            return [schema.to_openai_schema() for schema in schemas]
        if schema_format is ToolSchemaFormat.ANTHROPIC:
            return [schema.to_anthropic_schema() for schema in schemas]
        return schemas
