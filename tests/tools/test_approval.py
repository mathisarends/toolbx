import pytest
from pydantic import BaseModel

from toolbx import (
    ApprovalMiddleware,
    ErrorBoundaryMiddleware,
    Toolbox,
    ToolCall,
    ToolRequest,
    Toolset,
    tool,
)


class TransferParams(BaseModel):
    amount: float
    to: str


class BankTools(Toolset, namespace=None):
    def __init__(self) -> None:
        self.open = True

    @tool("Show the balance")
    def balance(self) -> str:
        return "100"

    @tool("Delete the account", requires_approval=True)
    def close(self) -> str:
        return "closed"

    @tool(
        "Transfer money",
        params=TransferParams,
        requires_approval=lambda params: params.amount > 100,
        available_when=lambda self: self.open,
    )
    def transfer(self, params: TransferParams) -> str:
        return f"sent {params.amount:g} to {params.to}"


class Recorder:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def __call__(self, call: ToolCall) -> bool:
        self.asked.append(call.name)
        return self.answer


@pytest.mark.asyncio
async def test_static_approval_asks_and_declined_calls_do_not_run() -> None:
    confirm = Recorder(answer=False)
    toolbox = Toolbox(toolsets=(BankTools(),), middleware=[ApprovalMiddleware(confirm)])

    assert await toolbox.execute(ToolRequest("balance")) == "100"
    assert (
        await toolbox.execute(ToolRequest("close")) == "Tool call declined by the user"
    )
    assert confirm.asked == ["close"]

    confirm.answer = True
    assert await toolbox.execute(ToolRequest("close")) == "closed"


@pytest.mark.asyncio
async def test_predicate_sees_validated_params() -> None:
    confirm = Recorder(answer=False)
    toolbox = Toolbox(
        toolsets=(BankTools(),),
        middleware=[ApprovalMiddleware(confirm, decline_message="No.")],
    )

    small = await toolbox.execute(
        ToolRequest("transfer", {"amount": "20", "to": "acct"})
    )
    large = await toolbox.execute(
        ToolRequest("transfer", {"amount": 500, "to": "acct"})
    )

    assert small == "sent 20 to acct"
    assert large == "No."
    assert confirm.asked == ["transfer"]
    assert toolbox["transfer"].approval_required({"amount": 101, "to": "x"})


@pytest.mark.asyncio
async def test_async_confirm_is_awaited() -> None:
    async def confirm(call: ToolCall) -> bool:
        return call.arguments["to"] == "trusted"

    toolbox = Toolbox(toolsets=(BankTools(),), middleware=[ApprovalMiddleware(confirm)])

    assert await toolbox.execute(
        ToolRequest("transfer", {"amount": 500, "to": "trusted"})
    ) == ("sent 500 to trusted")
    assert await toolbox.execute(
        ToolRequest("transfer", {"amount": 500, "to": "other"})
    ) == ("Tool call declined by the user")


@pytest.mark.asyncio
async def test_unknown_and_unavailable_tools_are_not_offered_for_approval() -> None:
    confirm = Recorder(answer=True)
    tools = BankTools()
    tools.open = False
    toolbox = Toolbox(toolsets=(tools,), middleware=[ApprovalMiddleware(confirm)])

    for name in ("missing", "transfer"):
        with pytest.raises(LookupError):
            await toolbox.execute(ToolRequest(name, {"amount": 500, "to": "x"}))
    assert confirm.asked == []


@pytest.mark.asyncio
async def test_invalid_arguments_fail_before_asking_the_user() -> None:
    confirm = Recorder(answer=True)
    toolbox = Toolbox(
        toolsets=(BankTools(),),
        middleware=[ErrorBoundaryMiddleware(), ApprovalMiddleware(confirm)],
    )

    result = await toolbox.execute(
        ToolRequest("transfer", {"amount": "lots", "to": "x"})
    )

    assert isinstance(result, str)
    assert result.startswith("Tool failed:")
    assert confirm.asked == []
