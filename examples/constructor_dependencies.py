import asyncio

from toolbox import Toolbox, Toolset, tool


class SearchClient:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def search(self, query: str) -> str:
        return f"{self.prefix}:{query}"


class SearchTools(Toolset):
    def __init__(self, client: SearchClient) -> None:
        self.client = client

    @tool("Search a configured source")
    async def search(self, query: str) -> str:
        return await self.client.search(query)


async def main() -> None:
    toolbox = Toolbox(SearchTools(SearchClient("docs")))
    print(await toolbox.execute("search_search", {"query": "toolbox"}))


if __name__ == "__main__":
    asyncio.run(main())
