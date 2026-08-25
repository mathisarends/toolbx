import asyncio
from dataclasses import dataclass

from agenttoolkit import Inject, ToolContext, Tools


@dataclass
class SearchClient:
    prefix: str


tools = Tools(context=ToolContext(SearchClient(prefix="kb:")))


# `Inject[SearchClient]` is resolved from the ToolContext at call time and
# never shows up in the tool's LLM-facing schema — only `query` does.
@tools.register("Search the knowledge base")
def search(query: str, client: Inject[SearchClient]) -> str:
    return f"{client.prefix}{query}"


async def main() -> None:
    print(tools.get_schema()[0].parameters)
    result = await tools.execute("search", {"query": "agenttoolkit"})
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
