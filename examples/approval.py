import asyncio

from pydantic import BaseModel, Field

from toolbox import Toolbox, Toolset
from toolbox import tool as mark_tool

toolbox = Toolbox()


class TransferParams(BaseModel):
    amount: float = Field(description="Amount to transfer")
    to: str = Field(description="Recipient account")


class DefinedTools1(Toolset, namespace=None):
    @mark_tool(
        "Transfer money between accounts (needs confirmation)", requires_approval=True
    )
    def transfer(self, params: TransferParams) -> str:
        return f"transferred {params.amount} to {params.to}"


toolbox.add(DefinedTools1())


async def main() -> None:
    tool = toolbox.get("transfer")
    assert tool is not None
    print("requires_approval:", tool.requires_approval)
    args = TransferParams(amount=50.0, to="acct-42")
    result = await toolbox.execute("transfer", args.model_dump())
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
