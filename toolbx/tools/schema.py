import inspect
from collections.abc import Callable
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, create_model


class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def build_schema(
    func: Callable | None = None,
    *,
    params_model: type[BaseModel] | None = None,
) -> dict[str, Any]:
    return _schema_model(func, params_model=params_model).model_json_schema(
        mode="validation"
    )


def _schema_model(
    func: Callable | None,
    *,
    params_model: type[BaseModel] | None,
) -> type[BaseModel]:
    if params_model is not None:
        return create_model(
            params_model.__name__,
            __base__=params_model,
            __config__=ConfigDict(extra="forbid"),
            __module__=params_model.__module__,
        )
    if func is None:
        raise ValueError("A callable or params_model is required")
    return _model_from_callable(func)


def _params_parameter(
    func: Callable, params_model: type[BaseModel] | None
) -> str | None:
    if params_model is None:
        return None
    parameters = inspect.signature(func).parameters
    get_type_hints(func, include_extras=True)
    if len(parameters) != 1:
        raise ValueError(
            f"Tool '{func.__name__}' uses params model '{params_model.__name__}' "
            "but has no unambiguous single parameter that can receive it"
        )
    name, parameter = next(iter(parameters.items()))
    if parameter.kind not in {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }:
        raise TypeError(f"Tool parameter '{name}' must accept a keyword argument")
    return name


def _model_from_callable(func: Callable) -> type[BaseModel]:
    signature = inspect.signature(func)
    hints = get_type_hints(func, include_extras=True)
    function_name = getattr(func, "__name__", type(func).__name__)
    fields: dict[str, Any] = {}
    descriptions: dict[str, str] = {}

    for name, parameter in signature.parameters.items():
        if name not in hints:
            raise TypeError(
                f"Tool '{function_name}' parameter '{name}' requires a type annotation"
            )
        annotation = hints[name]
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise TypeError(f"Tool '{function_name}' cannot use variadic parameters")

        default = (
            ... if parameter.default is inspect.Parameter.empty else parameter.default
        )
        fields[name] = (annotation, default)
        description = _annotated_description(annotation)
        if description is not None:
            descriptions[name] = description

    model = create_model(
        f"{function_name.title().replace('_', '')}Params",
        __config__=ConfigDict(extra="forbid", arbitrary_types_allowed=True),
        **fields,
    )
    for name, description in descriptions.items():
        model.model_fields[name].description = description
    model.model_rebuild(force=True)
    return model


def _annotated_description(annotation: Any) -> str | None:
    if get_origin(annotation) is not Annotated:
        return None
    return next(
        (
            metadata
            for metadata in get_args(annotation)[1:]
            if isinstance(metadata, str)
        ),
        None,
    )
