from typing import Any

from pydantic import BaseModel

from toolbx.tools.models import Tool


def resolve_arguments(tool: Tool, params: BaseModel) -> dict[str, Any]:
    if tool._params_parameter is not None:
        return {tool._params_parameter: params}
    return {name: getattr(params, name) for name in type(params).model_fields}
