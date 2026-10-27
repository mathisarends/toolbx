import asyncio
import datetime as dt
from dataclasses import dataclass

from pydantic import BaseModel, Field

from experiments.agent import Agent
from experiments.environments import Console
from experiments.model import experiment_model
from toolbx import CallLoggingMiddleware, Toolbox, Toolset, tool


@dataclass
class UserInfo:
    name: str
    is_admin: bool = False


class AddParams(BaseModel):
    a: float = Field(description="First addend")
    b: float = Field(description="Second addend")


class WeatherResult(BaseModel):
    city: str
    temp_c: float


_KNOWN_CITIES = {"berlin": 18.0, "hamburg": 15.5, "muenchen": 21.0}


class DemoTools(Toolset, namespace=None):
    def __init__(self, user: UserInfo) -> None:
        self.user = user

    @tool("Get the current date and time")
    def get_current_time(self) -> str:
        return dt.datetime.now().isoformat()

    @tool("Add two numbers", params=AddParams)
    def add(self, params: AddParams) -> float:
        return params.a + params.b

    @tool("Get information about the currently logged in user")
    def whoami(self) -> str:
        return f"{self.user.name} (admin={self.user.is_admin})"

    @tool("Reset the demo counter", available_when=lambda self: self.user.is_admin)
    def reset_counter(self) -> str:
        return "counter reset"

    @tool("Delete all demo data", requires_approval=True)
    def delete_all_data(self) -> str:
        return "all demo data deleted"

    @tool("Divide two numbers; fails on division by zero")
    def divide(self, a: float, b: float) -> float:
        return a / b

    @tool("Get the current weather for a known city")
    def get_weather(self, city: str) -> WeatherResult:
        temperature = _KNOWN_CITIES.get(city.lower())
        if temperature is None:
            raise ValueError(f"Unknown city: {city!r}")
        return WeatherResult(city=city, temp_c=temperature)


async def main() -> None:
    toolbox = Toolbox(
        DemoTools(UserInfo(name="Mathis", is_admin=True)),
        middleware=[CallLoggingMiddleware()],
    )
    console = Console(toolbox)
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
