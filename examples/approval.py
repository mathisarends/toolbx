import asyncio

from pydantic import BaseModel, Field

from toolbx import ApprovalMiddleware, Toolbox, ToolCall, Toolset, tool


class TransferParams(BaseModel):
    amount: float = Field(description="Amount to transfer")
    to: str = Field(description="Recipient account")


class BankTools(Toolset, namespace=None):
    @tool(
        "Transfer money between accounts",
        params=TransferParams,
        requires_approval=lambda params: params.amount > 100,
    )
    def transfer(self, params: TransferParams) -> str:
        return f"transferred {params.amount:g} to {params.to}"


async def confirm(call: ToolCall) -> bool:
    print(f"approve {call.name}({call.arguments})? -> no")
    return False


toolbox = Toolbox(BankTools(), middleware=[ApprovalMiddleware(confirm)])


async def main() -> None:
    print(await toolbox.execute("transfer", {"amount": 50, "to": "acct-42"}))
    print(await toolbox.execute("transfer", {"amount": 500, "to": "acct-42"}))


if __name__ == "__main__":
    asyncio.run(main())
