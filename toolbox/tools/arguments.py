import inspect
from typing import Any, get_type_hints

from pydantic import BaseModel

from toolbox.tools.models import Tool


def resolve_arguments(tool: Tool, params: BaseModel) -> dict[str, Any]:
    if tool.param_model is None:
        return {name: getattr(params, name) for name in type(params).model_fields}

    hints = get_type_hints(tool.fn, include_extras=True)
    candidates = list(inspect.signature(tool.fn).parameters)
    for name in candidates:
        if hints.get(name) == tool.param_model:
            return {name: params}
    if len(candidates) == 1:
        return {candidates[0]: params}
    raise ValueError(
        f"Tool '{tool.name}' uses params model '{tool.param_model.__name__}' "
        "but has no unambiguous parameter that can receive it"
    )
