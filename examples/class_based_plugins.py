"""Group related LLM tools in a class with constructor and call injection."""

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel, Field

from agenttoolkit import DependencyProvider, Inject, Tools, provide, tool


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


@dataclass(frozen=True)
class CallInfo:
    request_id: str


class Dependencies(DependencyProvider):
    @provide
    def call_info(self) -> CallInfo:
        # A real application would derive this from its active request.
        return CallInfo(request_id="request-42")


class SearchParams(BaseModel):
    query: str = Field(description="Text contained in the product name")
    limit: int = Field(default=5, ge=1, le=20)


class CatalogPlugin:
    """The LLM presentation layer in front of CatalogService."""

    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    @tool("Search the product catalog")
    async def search(
        self,
        params: SearchParams,
        call: Inject[CallInfo],
    ) -> dict[str, object]:
        products = await self._catalog.search(params.query, limit=params.limit)
        return {"request_id": call.request_id, "products": products}

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
    tools = Tools(dependencies=[Dependencies()])
    tools.add_plugin(CatalogPlugin(catalog), name="catalog")

    # The plugin namespace becomes part of each model-facing tool name.
    print([schema.name for schema in tools.get_schema()])

    async with tools:
        print(
            await tools.execute(
                "catalog_search",
                {"query": "keyboard", "limit": 2},
            )
        )
        print(await tools.execute("catalog_get", {"product_id": "p-3"}))


if __name__ == "__main__":
    asyncio.run(main())
