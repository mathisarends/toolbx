import asyncio
import datetime as dt
from dataclasses import dataclass

from pydantic import BaseModel, Field

from agenttoolkit.tools import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    Inject,
    Toolbox,
    ToolContext,
    description_from_context,
    requires,
)
from experiments.agent import Agent
from experiments.environments import Console
from experiments.model import experiment_model


@dataclass
class UserInfo:
    name: str
    is_admin: bool = False


context_user = UserInfo(name="Mathis", is_admin=True)
context = ToolContext(context_user)
toolbox = Toolbox(
    context=context,
    middleware=(ErrorBoundaryMiddleware(), CallLoggingMiddleware()),
)


@toolbox.tool("Get the current date and time")
def get_current_time() -> str:
    return dt.datetime.now().isoformat()


class AddParams(BaseModel):
    a: float = Field(description="First addend")
    b: float = Field(description="Second addend")


@toolbox.tool(
    "Add two numbers together",
    status=lambda params: f"Adding {params.a} + {params.b}",
)
def add(params: AddParams) -> float:
    return params.a + params.b


# 3. Dependency resolved from the ToolContext via Inject — never exposed to
#    the LLM as a schema field, only visible to the function body.
@toolbox.tool("Get information about the currently logged in user")
def whoami(user: Inject[UserInfo]) -> str:
    return f"{user.name} (admin={user.is_admin})"


# 4. Availability gated on a dependency in the ToolContext — the tool is
#    hidden from the schema entirely unless the predicate holds.
@toolbox.tool(
    "Reset the demo counter (admin only)",
    available_when=requires(UserInfo, predicate=lambda user: user.is_admin),
)
def reset_counter() -> str:
    return "counter reset"


# 5. Description resolved dynamically from the ToolContext, falling back to
#    a static description when the dependency isn't provided.
@toolbox.tool(
    description_from_context(
        UserInfo,
        render=lambda user: f"Greet {user.name} by name",
        fallback="Greet the user by name",
    )
)
def greet(user: Inject[UserInfo]) -> str:
    return f"Hello, {user.name}!"


# 6. Dangerous tool requiring explicit approval before the agent runs it.
@toolbox.tool(
    "Delete all demo data (dangerous, needs confirmation)", requires_approval=True
)
def delete_all_data() -> str:
    return "all demo data deleted"


# 7. Tool that can raise; the built-in error boundary returns the error text
#    to the agent instead of crashing the loop.
@toolbox.tool("Divide two numbers; fails on division by zero")
def divide(a: float, b: float) -> float:
    return a / b


# 8. Structured values pass through the tool pipeline unchanged.
_KNOWN_CITIES = {"berlin": 18.0, "hamburg": 15.5, "muenchen": 21.0}


class WeatherResult(BaseModel):
    city: str
    temp_c: float


@toolbox.tool("Get the current weather for a known city")
def get_weather(city: str) -> WeatherResult:
    temp_c = _KNOWN_CITIES.get(city.lower())
    if temp_c is None:
        raise ValueError(f"Unknown city: {city!r}")
    return WeatherResult(city=city, temp_c=temp_c)


async def main() -> None:
    console = Console(toolbox, context=context)
    model = experiment_model("gpt-5.6-terra", on_retry=console.on_retry)
    agent = Agent(
        model,
        toolbox,
        system_prompt="You are a helpful assistant.",
        on_tool_call=console.on_tool_call,
        on_tool_result=console.on_tool_result,
        confirm=console.confirm,
    )

    console.print_tools()
    await console.run(agent, "Chat gestartet. 'exit' zum Beenden.")


if __name__ == "__main__":
    asyncio.run(main())
