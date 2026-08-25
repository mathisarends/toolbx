import asyncio

from pydantic import BaseModel, Field

from agenttoolkit import StructuredOutputTools


class MultiplyParams(BaseModel):
    left: int
    right: int


class AgentResponse(BaseModel):
    reasoning: str = Field(description="Why this tool should be called")


tools = StructuredOutputTools()


@tools.tool("Multiply two integers")
def multiply(params: MultiplyParams) -> int:
    return params.left * params.right


async def main() -> None:
    [MultiplyTool] = tools.create_tool_models(base_model=AgentResponse)

    # Pass MultiplyTool to an LLM client as its structured-output model.
    response = MultiplyTool.model_validate(
        {
            "reasoning": "The user asked for the product.",
            "multiply": {"left": 6, "right": 7},
        }
    )

    result = await tools.execute("multiply", response.multiply.model_dump())
    print(MultiplyTool.model_json_schema())
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
