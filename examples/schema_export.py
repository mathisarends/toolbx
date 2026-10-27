import asyncio

from pydantic import BaseModel, Field

from toolbox import Toolbox

toolbox = Toolbox()


class SearchParams(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, ge=1)


@toolbox.tool("Search the documentation")
def search(params: SearchParams) -> None:
    pass


async def main() -> None:
    # Provider-neutral form: name/description/parameters, usable to hand-roll
    # an adapter for a client not covered by the two below.
    native = toolbox.schemas()[0]
    print("native:", native.model_dump())

    openai = toolbox.to_openai()[0]
    print("openai:", openai)

    anthropic = toolbox.to_anthropic()[0]
    print("anthropic:", anthropic)


if __name__ == "__main__":
    asyncio.run(main())
