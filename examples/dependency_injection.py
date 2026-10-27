import asyncio
from dataclasses import dataclass

from agenttoolkit import (
    DependencyProvider,
    Inject,
    Toolbox,
    provide,
)


@dataclass
class SearchClient:
    prefix: str


class Dependencies(DependencyProvider):
    @provide
    def search_client(self) -> SearchClient:
        return SearchClient(prefix="kb:")


toolbox = Toolbox(dependencies=[Dependencies()])


# Dependencies are resolved from the container and omitted from the schema.
@toolbox.tool("Search the knowledge base")
def search(
    query: str,
    client: Inject[SearchClient],
) -> str:
    return f"{client.prefix}{query}"


async def main() -> None:
    print(toolbox.get_schema()[0].parameters)
    result = await toolbox.execute("search", {"query": "agenttoolkit"})
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
