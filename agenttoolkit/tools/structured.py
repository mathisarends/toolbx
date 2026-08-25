from collections.abc import Iterable
from typing import overload

from pydantic import BaseModel, ConfigDict, Field, create_model

from agenttoolkit.tools.context import ToolContext
from agenttoolkit.tools.registry import ToolRegistry


class StructuredOutputTools(ToolRegistry):
    """Tools exposed as mutually exclusive structured-output models."""

    @overload
    def create_tool_models[ModelT: BaseModel](
        self,
        include_tools: Iterable[str] | None = None,
        *,
        base_model: type[ModelT],
        context: ToolContext | None = None,
    ) -> list[type[ModelT]]: ...

    @overload
    def create_tool_models(
        self,
        include_tools: Iterable[str] | None = None,
        *,
        context: ToolContext | None = None,
    ) -> list[type[BaseModel]]: ...

    def create_tool_models(
        self,
        include_tools: Iterable[str] | None = None,
        *,
        base_model: type[BaseModel] = BaseModel,
        context: ToolContext | None = None,
    ) -> list[type[BaseModel]]:
        """Build one structured-output model per available tool."""
        included = None if include_tools is None else frozenset(include_tools)
        models: list[type[BaseModel]] = []
        active_context = self._context if context is None else context

        for tool in self._tools.values():
            if not tool.is_available(active_context):
                continue
            if included is not None and tool.name not in included:
                continue
            models.append(
                create_model(
                    f"{tool.name.title().replace('_', '')}Tool",
                    __base__=base_model,
                    __config__=ConfigDict(extra="forbid"),
                    **{
                        tool.name: (
                            tool.input_model,
                            Field(
                                ...,
                                description=tool.resolve_description(active_context),
                            ),
                        )
                    },
                )
            )

        return models
