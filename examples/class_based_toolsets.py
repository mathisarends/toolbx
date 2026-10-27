"""Group LLM tools in an externally constructed Toolset instance."""

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel, Field

from toolbx import Toolbox, Toolset, to_text, tool


@dataclass(frozen=True)
class Product:
    id: str
    name: str


class CatalogService:
    """A regular application service, independent of the LLM tool API."""

    def __init__(self, products: list[Product]) -> None:
        self._products = products

    async def search(self, query: str, *, limit: int) -> list[Product]:
        query = query.casefold()
        matches = [item for item in self._products if query in item.name.casefold()]
        return matches[:limit]

    async def get(self, product_id: str) -> Product | None:
        return next((item for item in self._products if item.id == product_id), None)


class SearchParams(BaseModel):
    query: str = Field(description="Text contained in the product name")
    limit: int = Field(default=5, ge=1, le=20)


class CatalogTools(Toolset):
    """The LLM presentation layer in front of CatalogService."""

    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    @tool("Search the product catalog", params=SearchParams)
    async def search(
        self,
        params: SearchParams,
    ) -> list[Product]:
        return await self._catalog.search(params.query, limit=params.limit)

    @tool("Get one product by its stable identifier", name="get")
    async def get_product(self, product_id: str) -> Product | None:
        return await self._catalog.get(product_id)

    def normalize_query(self, query: str) -> str:
        # Helpers without @tool remain private to the model.
        return " ".join(query.split())


async def main() -> None:
    catalog = CatalogService(
        [
            Product("p-1", "Mechanical Keyboard"),
            Product("p-2", "Ergonomic Keyboard"),
            Product("p-3", "USB-C Dock"),
        ]
    )
    toolbox = Toolbox(CatalogTools(catalog))

    # The toolset namespace becomes part of each model-facing tool name.
    print([schema.name for schema in toolbox.schemas()])

    # to_text renders results the way a tool-result message expects them.
    found = await toolbox.execute("catalog_search", {"query": "keyboard", "limit": 2})
    print(to_text(found))
    print(to_text(await toolbox.execute("catalog_get", {"product_id": "p-3"})))

    # A narrower view, e.g. for a sub-agent that may only look up products.
    lookup = toolbox.subset(names={"catalog_get"})
    print(lookup.names())


if __name__ == "__main__":
    asyncio.run(main())
