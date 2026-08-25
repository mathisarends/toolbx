"""Expose class-based plugins as structured-output tool models."""

import asyncio
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, Field

from agenttoolkit import StructuredOutputTools, tool


@dataclass(frozen=True)
class Product:
    id: str
    name: str


class CatalogService:
    def __init__(self, products: list[Product]) -> None:
        self._products = products

    async def search(self, query: str, *, limit: int) -> list[Product]:
        query = query.casefold()
        matches = [item for item in self._products if query in item.name.casefold()]
        return matches[:limit]


class CatalogPlugin:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    @tool("Search the product catalog")
    async def search(
        self,
        query: Annotated[str, "Text contained in the product name"],
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
    ) -> list[Product]:
        return await self._catalog.search(query, limit=limit)


class AgentResponse(BaseModel):
    """Fields returned by the model alongside every selected tool."""

    reasoning: str = Field(description="Why this tool is the next step")


async def main() -> None:
    catalog = CatalogService(
        [
            Product("p-1", "Mechanical Keyboard"),
            Product("p-2", "Ergonomic Keyboard"),
            Product("p-3", "USB-C Dock"),
        ]
    )
    tools = StructuredOutputTools()
    tools.add_plugin(CatalogPlugin(catalog), name="catalog")

    # Give these generated models to an LLM as its structured-output choices.
    [CatalogSearchTool] = tools.create_tool_models(base_model=AgentResponse)

    # This simulates the structured response returned by the LLM.
    response = CatalogSearchTool.model_validate(
        {
            "reasoning": "The user is looking for keyboards.",
            "catalog_search": {"query": "keyboard", "limit": 2},
        }
    )

    arguments = response.catalog_search.model_dump()
    result = await tools.execute("catalog_search", arguments)

    print(CatalogSearchTool.model_json_schema())
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
