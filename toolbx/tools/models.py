import asyncio
import inspect
from collections.abc import Callable, Collection, Mapping
from copy import deepcopy
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from toolbx.tools.schema import ToolSchema, _params_parameter, _schema_model
from toolbx.tools.toolset import require_valid_name


class Tool:
    def __init__(
        self,
        name: str,
        description: str | None,
        fn: Callable[..., object],
        *,
        params_model: type[BaseModel] | None = None,
        tags: Collection[str] = (),
        metadata: Mapping[str, Any] | None = None,
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
        self.params_model = params_model
        self._params_parameter = _params_parameter(fn, params_model)
        self.tags = frozenset(tags)
        self.metadata: Mapping[str, Any] = MappingProxyType(dict(metadata or {}))
        self.requires_approval = requires_approval
        self.available_when = available_when
        self.namespace = namespace
        self.local_name = local_name
        self._input_model = _schema_model(fn, params_model=params_model)
        self.input_schema = self._input_model.model_json_schema(mode="validation")

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
            input_schema=deepcopy(self.input_schema),
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
