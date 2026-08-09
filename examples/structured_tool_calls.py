import asyncio

from pydantic import BaseModel, Field

from agenttoolkit import StructuredOutputTools


class MultiplyParams(BaseModel):
    left: int
    right: int


class AgentAction(BaseModel):
    reasoning: str = Field(description="Why this tool should be called")


tools = StructuredOutputTools()


@tools.action("Multiply two integers", params=MultiplyParams)
def multiply(params: MultiplyParams) -> int:
    return params.left * params.right


async def main() -> None:
    [MultiplyAction] = tools.create_action_model(base_model=AgentAction)

    # Pass MultiplyAction to an LLM client as its structured-output model.
    action = MultiplyAction.model_validate(
        {
            "reasoning": "The user asked for the product.",
            "multiply": {"left": 6, "right": 7},
        }
    )

    result = await tools.execute("multiply", action.multiply.model_dump())
    print(MultiplyAction.model_json_schema())
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
