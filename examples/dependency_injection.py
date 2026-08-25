import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from agenttoolkit import (
    DependencyProvider,
    Inject,
    Scope,
    Tools,
    provide,
)


@dataclass
class SearchClient:
    prefix: str


class Dependencies(DependencyProvider):
    @provide(scope=Scope.APP)
    def search_client(self) -> SearchClient:
        return SearchClient(prefix="kb:")

    @provide
    async def request_id(self) -> AsyncIterator[str]:
        yield "request-1"


tools = Tools(dependencies=[Dependencies()])


# Dependencies are resolved from the container and omitted from the schema.
@tools.tool("Search the knowledge base")
def search(
    query: str,
    client: Inject[SearchClient],
    request_id: Inject[str],
) -> str:
    return f"{request_id}:{client.prefix}{query}"


async def main() -> None:
    print(tools.get_schema()[0].parameters)
    async with tools:
        result = await tools.execute("search", {"query": "agenttoolkit"})
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
