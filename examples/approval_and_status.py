import asyncio

from pydantic import BaseModel, Field

from agenttoolkit import Tools

tools = Tools()


class TransferParams(BaseModel):
    amount: float = Field(description="Amount to transfer")
    to: str = Field(description="Recipient account")


# `status` renders a human-readable line for the arguments an agent is about
# to call the tool with, before execution — handy for approval prompts and
# activity logs. It accepts a plain string or a callable taking the params.
@tools.tool(
    "Transfer money between accounts (needs confirmation)",
    status=lambda params: f"Transferring {params.amount} to {params.to}",
    requires_approval=True,
)
def transfer(params: TransferParams) -> str:
    return f"transferred {params.amount} to {params.to}"


async def main() -> None:
    tool = tools.get("transfer")
    assert tool is not None

    args = TransferParams(amount=50.0, to="acct-42")
    print("status:", tool.format_status(args))
    print("requires_approval:", tool.requires_approval)

    # `Tools.execute` itself does not gate on `requires_approval` — that's an
    # agent-loop concern (see experiments/agent.py's `confirm` callback).
    # A caller decides whether to ask first, using this flag and the status.
    result = await tools.execute("transfer", args.model_dump())
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
