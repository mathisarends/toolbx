import asyncio

from pydantic import BaseModel, Field

from agenttoolkit import Toolbox

toolbox = Toolbox()


class TransferParams(BaseModel):
    amount: float = Field(description="Amount to transfer")
    to: str = Field(description="Recipient account")


@toolbox.tool(
    "Transfer money between accounts (needs confirmation)",
    requires_approval=True,
)
def transfer(params: TransferParams) -> str:
    return f"transferred {params.amount} to {params.to}"


async def main() -> None:
    tool = toolbox.get("transfer")
    assert tool is not None
    print("requires_approval:", tool.requires_approval)

    # `Toolbox.execute` itself does not gate on `requires_approval` — that's an
    # agent-loop concern (see experiments/agent.py's `confirm` callback).
    args = TransferParams(amount=50.0, to="acct-42")
    result = await toolbox.execute("transfer", args.model_dump())
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
