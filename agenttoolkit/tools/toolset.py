import inspect
import re
from dataclasses import dataclass

from agenttoolkit.tools.plugins import ToolDefinition, get_tool_definition

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class ToolEntry:
    attribute_name: str
    local_name: str
    definition: ToolDefinition


def require_valid_name(value: str, what: str) -> None:
    if not value or _NAME.fullmatch(value) is None:
        raise ValueError(f"{what} must contain only letters, numbers, '_' or '-'")


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
        entries.append(ToolEntry(attribute_name, local_name, definition))
    return tuple(entries)
