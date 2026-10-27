import inspect
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from toolbox.tools.binding import ToolAvailability, ToolDescription
from toolbox.tools.context import ToolContext
from toolbox.tools.schema import ToolSchema, _infer_param_model, _schema_model


class ToolSchemaFormat(StrEnum):
    NATIVE = "native"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    """Runtime hints which do not belong in an LLM function schema."""

    tags: frozenset[str] = field(default_factory=frozenset)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", frozenset(self.tags))
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))


class Tool:
    def __init__(
        self,
        name: str,
        description: str | ToolDescription | None,
        fn: Callable[..., object],
        *,
        param_model: type[BaseModel] | None = None,
        parameters: Mapping[str, Any] | None = None,
        metadata: ToolMetadata | None = None,
        requires_approval: bool = False,
        available_when: ToolAvailability | None = None,
        plugin_name: str | None = None,
        local_name: str | None = None,
    ) -> None:
        if not name:
            raise ValueError("Tool name cannot be empty")
        self.name = name
        self.description = "" if description is None else description
        self.fn = fn
        self.param_model = param_model or _infer_param_model(fn)
        self._metadata = metadata or ToolMetadata()
        self.requires_approval = requires_approval
        self.available_when = available_when
        self.plugin_name = plugin_name
        self.local_name = local_name
        self.input_model = _schema_model(fn, param_model=self.param_model)
        self.parameters = (
            deepcopy(dict(parameters))
            if parameters is not None
            else self.input_model.model_json_schema(mode="validation")
        )

    @property
    def tags(self) -> frozenset[str]:
        return self._metadata.tags

    @property
    def extra(self) -> Mapping[str, Any]:
        return self._metadata.extra

    def is_available(self, context: ToolContext | None = None) -> bool:
        return True if self.available_when is None else self.available_when(context)

    def resolve_description(self, context: ToolContext | None = None) -> str:
        if isinstance(self.description, ToolDescription):
            return self.description.resolve(context)
        return self.description

    def to_schema(self, context: ToolContext | None = None) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.resolve_description(context),
            parameters=self.parameters,
        )

    def to_openai_schema(
        self,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        return self.to_schema(context).to_openai_schema()

    def to_anthropic_schema(
        self,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        return self.to_schema(context).to_anthropic_schema()

    def parse_arguments(self, arguments: str) -> dict[str, Any]:
        raw_arguments = json.loads(arguments)
        params = self.input_model.model_validate(raw_arguments)
        return params.model_dump(mode="python")

    async def execute(self, arguments: dict[str, Any]) -> object:
        result = self.fn(**arguments)
        return await result if inspect.isawaitable(result) else result

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Tool) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)
