from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from toolbx import Toolbox, Toolset, build_schema, tool


class Address(BaseModel):
    city: str
    zip_code: str | None = None


class Person(BaseModel):
    title: str
    address: Address
    nickname: str = "none"


class Node(BaseModel):
    value: int
    children: list[Node] = []


class PeopleTools(Toolset, namespace=None):
    def __init__(self) -> None:
        self.received: list[Person] = []

    @tool("Create a person", params=Person)
    def create(self, person: Person) -> str:
        self.received.append(person)
        return person.nickname

    @tool("Count items")
    def get_HTTP(self, limit: int = 10, tag: str | None = None) -> str:
        return f"{limit}:{tag}"


def _contains_key(node: Any, key: str) -> bool:
    if isinstance(node, dict):
        return key in node or any(_contains_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_contains_key(item, key) for item in node)
    return False


def test_schemas_omit_pydantic_titles_but_keep_a_title_property() -> None:
    schema = Toolbox(PeopleTools())["create"].input_schema

    assert "title" not in schema
    assert "title" not in schema["properties"]["nickname"]
    assert "title" not in schema["$defs"]["Address"]
    assert set(schema["properties"]) == {"title", "address", "nickname"}
    assert schema["properties"]["title"] == {"type": "string"}


def test_data_values_named_title_are_preserved() -> None:
    def search(filters: dict[str, str] = {"title": "kept"}) -> None:  # noqa: B006
        pass

    schema = build_schema(search)
    assert schema["properties"]["filters"]["default"] == {"title": "kept"}


def test_inline_refs_replaces_defs_and_rejects_recursion() -> None:
    schema = Toolbox(PeopleTools()).schemas()[0]
    inlined = schema.inline_refs().input_schema

    assert not _contains_key(inlined, "$ref")
    assert "$defs" not in inlined
    assert inlined["properties"]["address"]["properties"]["city"] == {"type": "string"}
    assert "$defs" in schema.input_schema

    class Trees(Toolset, namespace=None):
        @tool("Walk a tree", params=Node)
        def walk(self, node: Node) -> None:
            pass

    with pytest.raises(ValueError, match="'Node' is recursive"):
        Toolbox(Trees()).schemas()[0].inline_refs()


def test_strict_openai_export_requires_all_fields_and_nullable_optionals() -> None:
    exported = {
        item["function"]["name"]: item["function"]
        for item in Toolbox(PeopleTools()).to_openai(strict=True)
    }
    create = exported["create"]
    parameters = create["parameters"]
    address = parameters["$defs"]["Address"]

    assert create["strict"] is True
    assert parameters["additionalProperties"] is False
    assert parameters["required"] == ["title", "address", "nickname"]
    assert parameters["properties"]["nickname"]["anyOf"][1] == {"type": "null"}
    assert parameters["properties"]["title"] == {"type": "string"}
    assert address["additionalProperties"] is False
    assert address["required"] == ["city", "zip_code"]
    assert "anyOf" in address["properties"]["zip_code"]
    assert len(address["properties"]["zip_code"]["anyOf"]) == 2

    count = exported["get_HTTP"]["parameters"]
    assert count["required"] == ["limit", "tag"]
    assert "strict" not in Toolbox(PeopleTools()).to_openai()[0]["function"]


@pytest.mark.asyncio
async def test_strict_nulls_for_optional_fields_fall_back_to_defaults() -> None:
    tools = PeopleTools()
    toolbox = Toolbox(tools)

    result = await toolbox.execute(
        "create",
        {
            "title": "Dr",
            "address": {"city": "Berlin", "zip_code": None},
            "nickname": None,
        },
    )
    assert result == "none"
    assert tools.received[0].address.zip_code is None

    assert await toolbox.execute("get_HTTP", {"limit": None, "tag": None}) == (
        "10:None"
    )


@pytest.mark.asyncio
async def test_null_for_a_required_field_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="title"):
        await Toolbox(PeopleTools()).execute(
            "create", {"title": None, "address": {"city": "Berlin"}}
        )


@pytest.mark.asyncio
async def test_nulls_inside_lists_of_nested_models_are_dropped() -> None:
    seen: list[Node] = []

    class Trees(Toolset, namespace=None):
        @tool("Walk a tree", params=Node)
        def walk(self, node: Node) -> None:
            seen.append(node)

    await Toolbox(Trees()).execute(
        "walk", {"value": 1, "children": [{"value": 2, "children": None}]}
    )
    assert seen[0].children[0].children == []


def test_generated_model_names_keep_acronyms() -> None:
    assert Toolbox(PeopleTools())["get_HTTP"]._input_model.__name__ == "GetHTTPParams"
