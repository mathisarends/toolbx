import asyncio
import inspect
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from toolbox.tools.schema import ToolSchema, _schema_model
from toolbox.tools.toolset import require_valid_name


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
        description: str | None,
        fn: Callable[..., object],
        *,
        param_model: type[BaseModel] | None = None,
        metadata: ToolMetadata | None = None,
        requires_approval: bool = False,
        available_when: Callable[[Any], bool] | None = None,
        namespace: str | None = None,
        local_name: str | None = None,
    ) -> None:
        if not name:
            raise ValueError("Tool name cannot be empty")
        require_valid_name(name, "Tool name")
        self.name = name
        self.description = "" if description is None else description
        self.fn = fn
        self.param_model = param_model
        self._metadata = metadata or ToolMetadata()
        self.requires_approval = requires_approval
        self.available_when = available_when
        self.namespace = namespace
        self.local_name = local_name
        self.input_model = _schema_model(fn, param_model=self.param_model)
        self.parameters = self.input_model.model_json_schema(mode="validation")

    @property
    def tags(self) -> frozenset[str]:
        return self._metadata.tags

    @property
    def extra(self) -> Mapping[str, Any]:
        return self._metadata.extra

    def is_available(self) -> bool:
        return (
            True
            if self.available_when is None
            else self.available_when(self.fn.__self__)
        )

    def to_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters=deepcopy(self.parameters),
        )

    def to_openai_schema(
        self,
    ) -> dict[str, Any]:
        return self.to_schema().to_openai_schema()

    def to_anthropic_schema(
        self,
    ) -> dict[str, Any]:
        return self.to_schema().to_anthropic_schema()

    async def _invoke(self, arguments: dict[str, Any]) -> object:
        if inspect.iscoroutinefunction(self.fn):
            result = self.fn(**arguments)
        else:
            result = await asyncio.to_thread(self.fn, **arguments)
        return await result if inspect.isawaitable(result) else result

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Tool) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)
