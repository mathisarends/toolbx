import asyncio

from pydantic import BaseModel, Field

from toolbox import Toolbox, Toolset
from toolbox import tool as mark_tool

toolbox = Toolbox()


class SearchParams(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, ge=1)


class DefinedTools1(Toolset, namespace=None):
    @mark_tool("Search the documentation")
    def search(self, params: SearchParams) -> None:
        pass


toolbox.add(DefinedTools1())


async def main() -> None:
    native = toolbox.schemas()[0]
    print("native:", native.model_dump())
    openai = toolbox.to_openai()[0]
    print("openai:", openai)
    anthropic = toolbox.to_anthropic()[0]
    print("anthropic:", anthropic)


if __name__ == "__main__":
    asyncio.run(main())
