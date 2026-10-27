import inspect
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from toolbox.dependency import DependencyContainer
from toolbox.tools.context import _INJECT_MARKER, ToolContext
from toolbox.tools.models import Tool


async def resolve_arguments(
    tool: Tool,
    params: BaseModel,
    container: DependencyContainer | None,
    context: ToolContext | None,
) -> dict[str, Any]:
    kwargs = _tool_arguments(tool, params)
    hints = get_type_hints(tool.fn, include_extras=True)

    for name, parameter in inspect.signature(tool.fn).parameters.items():
        annotation = hints.get(name)
        if annotation is None or not _is_injected(annotation):
            continue
        expected_type = get_args(annotation)[0]
        dependency = None
        found = False
        if container is not None and container.has(expected_type):
            dependency = await container.get(expected_type)
            found = True
        elif context is not None:
            dependency = context.resolve(expected_type)
            found = dependency is not None
        if not found:
            if parameter.default is inspect.Parameter.empty:
                type_name = getattr(expected_type, "__name__", repr(expected_type))
                raise ValueError(
                    f"Missing injected dependency for parameter '{name}' "
                    f"of type '{type_name}'"
                )
            continue
        kwargs[name] = dependency

    return kwargs


def _tool_arguments(tool: Tool, params: BaseModel) -> dict[str, Any]:
    if tool.param_model is None:
        return {name: getattr(params, name) for name in type(params).model_fields}

    hints = get_type_hints(tool.fn, include_extras=True)
    candidates: list[str] = []
    for name in inspect.signature(tool.fn).parameters:
        if name in {"self", "cls"}:
            continue
        annotation = hints.get(name)
        if annotation is not None and _is_injected(annotation):
            continue
        candidates.append(name)
        if annotation == tool.param_model:
            return {name: params}

    if len(candidates) == 1:
        return {candidates[0]: params}
    raise ValueError(
        f"Tool '{tool.name}' uses params model '{tool.param_model.__name__}' "
        "but has no unambiguous parameter that can receive it"
    )


def _is_injected(annotation: Any) -> bool:
    return get_origin(annotation) is Annotated and _INJECT_MARKER in get_args(
        annotation
    )
