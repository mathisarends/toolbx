import asyncio

from toolbx import Toolbox, Toolset, tool


class AdminTools(Toolset, namespace=None):
    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    @tool("Reset the counter", available_when=lambda self: self.enabled)
    def reset(self) -> str:
        return "counter reset"


async def main() -> None:
    tools = AdminTools()
    toolbox = Toolbox(tools)
    print("disabled:", [schema.name for schema in toolbox.schemas()])
    tools.enabled = True
    print("enabled:", [schema.name for schema in toolbox.schemas()])
    print(await toolbox.execute("reset"))
    tools.enabled = False
    print("disabled again:", [schema.name for schema in toolbox.schemas()])


if __name__ == "__main__":
    asyncio.run(main())
