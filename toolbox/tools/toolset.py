import inspect
import re
from dataclasses import dataclass
from types import EllipsisType
from typing import Any, ClassVar

from toolbox.tools.plugins import ToolDefinition, get_tool_definition
from toolbox.tools.schema import build_schema

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NAMESPACE_SUFFIXES = ("Toolset", "Toolbox", "Tools", "Plugin")


@dataclass(frozen=True, slots=True)
class ToolEntry:
    attribute_name: str
    local_name: str
    definition: ToolDefinition


def require_valid_name(value: str, what: str) -> None:
    if not value or _NAME.fullmatch(value) is None:
        raise ValueError(f"{what} must contain only letters, numbers, '_' or '-'")
    if len(value) > 64:
        raise ValueError(f"{what} must contain at most 64 characters")


def collect_tool_entries(cls: type) -> tuple[ToolEntry, ...]:
    """Find the ``@tool`` methods of a class, validated without an instance."""
    attribute_names = dict.fromkeys(
        attribute_name
        for base in reversed(cls.__mro__[:-1])
        for attribute_name in vars(base)
    )

    entries: list[ToolEntry] = []
    local_names: set[str] = set()
    for attribute_name in attribute_names:
        descriptor = inspect.getattr_static(cls, attribute_name)
        definition = get_tool_definition(descriptor)
        if isinstance(descriptor, (classmethod, staticmethod)):
            if definition is None:
                definition = get_tool_definition(descriptor.__func__)
            if definition is not None:
                raise TypeError(
                    f"Plugin tool '{attribute_name}' must be an instance method"
                )
            continue
        if definition is None:
            continue
        if not inspect.isfunction(descriptor):
            raise TypeError(
                f"Plugin tool '{attribute_name}' must be an instance method"
            )

        local_name = attribute_name if definition.name is None else definition.name
        require_valid_name(local_name, "Plugin tool name")
        if local_name in local_names:
            raise ValueError(f"{cls.__name__} defines duplicate tool '{local_name}'")
        local_names.add(local_name)
        method = descriptor.__get__(object(), cls)
        if any(
            parameter.kind
            in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            for parameter in inspect.signature(method).parameters.values()
        ):
            raise TypeError(f"Tool '{attribute_name}' cannot use variadic parameters")
        build_schema(method, param_model=definition.params)
        entries.append(ToolEntry(attribute_name, local_name, definition))
    return tuple(entries)


def default_namespace(class_name: str) -> str:
    for suffix in _NAMESPACE_SUFFIXES:
        if class_name.endswith(suffix) and class_name != suffix:
            class_name = class_name.removesuffix(suffix)
            break
    return _WORD_BOUNDARY.sub("_", class_name).lower()


class Toolset:
    """Base class for grouping ``@tool`` methods that share constructor state.

    The namespace prefixes every exposed tool name. It defaults to the
    snake_case class name without a ``Toolset``/``Toolbox``/``Tools``/``Plugin`` suffix;
    ``namespace=None`` exposes the tools without a prefix.
    """

    namespace: ClassVar[str | None] = None

    def __init_subclass__(
        cls,
        *,
        namespace: str | EllipsisType | None = ...,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if namespace is ...:
            namespace = default_namespace(cls.__name__)
        if namespace is not None:
            require_valid_name(namespace, "Namespace")
        cls.namespace = namespace
        collect_tool_entries(cls)
