from collections.abc import Callable
from copy import deepcopy
from typing import Any

# Keys whose values are maps of user-chosen names, so a property called
# "title" is never mistaken for the schema keyword.
_NAME_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions"})
# Keys whose values are data, not subschemas.
_DATA_KEYS = frozenset({"default", "examples", "const", "enum"})


def strip_titles(node: Any) -> Any:
    if isinstance(node, list):
        return [strip_titles(item) for item in node]
    if not isinstance(node, dict):
        return node
    kept = {
        key: value
        for key, value in node.items()
        if not (key == "title" and isinstance(value, str))
    }
    return _map_subschemas(kept, strip_titles)


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    definitions = schema.get("$defs", {})

    def resolve(node: Any, active: tuple[str, ...]) -> Any:
        if isinstance(node, list):
            return [resolve(item, active) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.removeprefix("#/$defs/")
            if name in active:
                raise ValueError(f"Schema '{name}' is recursive and cannot be inlined")
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            return {**resolve(definitions[name], (*active, name)), **siblings}
        kept = {key: value for key, value in node.items() if key != "$defs"}
        return _map_subschemas(kept, lambda child: resolve(child, active))

    return resolve(schema, ())


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adapt a schema to OpenAI strict mode.

    Strict mode requires every property to be listed in ``required``, so an
    optional property becomes nullable instead; ``drop_omitted_nulls`` turns
    those nulls back into omissions before validation.
    """

    def convert(node: Any) -> Any:
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        converted = _map_subschemas(node, convert)
        properties = converted.get("properties")
        if converted.get("type") == "object" and isinstance(properties, dict):
            required = set(converted.get("required", ()))
            for name, prop in properties.items():
                if name not in required and not _allows_null(prop, schema):
                    properties[name] = {"anyOf": [prop, {"type": "null"}]}
            converted["required"] = list(properties)
            converted["additionalProperties"] = False
        return converted

    return convert(schema)


def _map_subschemas(
    node: dict[str, Any], convert: Callable[[Any], Any]
) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DATA_KEYS:
            mapped[key] = deepcopy(value)
        elif key in _NAME_MAPS and isinstance(value, dict):
            mapped[key] = {name: convert(sub) for name, sub in value.items()}
        else:
            mapped[key] = convert(value)
    return mapped


def drop_omitted_nulls(value: Any, schema: dict[str, Any]) -> Any:
    """Remove nulls sent for optional properties that do not accept null."""

    def walk(node: Any, subschema: Any) -> Any:
        subschema = _resolve(subschema, schema)
        if not isinstance(subschema, dict):
            return node
        if isinstance(node, dict) and isinstance(subschema.get("properties"), dict):
            properties = subschema["properties"]
            required = set(subschema.get("required", ()))
            return {
                key: walk(item, properties.get(key))
                for key, item in node.items()
                if not (
                    item is None
                    and key in properties
                    and key not in required
                    and not _allows_null(properties[key], schema)
                )
            }
        if isinstance(node, list) and isinstance(subschema.get("items"), dict):
            return [walk(item, subschema["items"]) for item in node]
        return node

    return walk(value, schema)


def _resolve(node: Any, root: dict[str, Any]) -> Any:
    seen: set[str] = set()
    while isinstance(node, dict) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        if ref in seen or not ref.startswith("#/$defs/"):
            break
        seen.add(ref)
        node = root.get("$defs", {}).get(ref.removeprefix("#/$defs/"), node)
    return node


def _allows_null(node: Any, root: dict[str, Any]) -> bool:
    node = _resolve(node, root)
    if not isinstance(node, dict):
        return True
    kind = node.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    return any(
        _allows_null(option, root)
        for key in ("anyOf", "oneOf")
        for option in node.get(key, ())
    )
