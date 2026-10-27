import asyncio
from dataclasses import dataclass

from agenttoolkit import Toolbox, ToolContext, provided, requires


@dataclass
class UserInfo:
    name: str
    is_admin: bool = False


toolbox = Toolbox(context=ToolContext(UserInfo(name="Mathis")))


# Hidden entirely unless a UserInfo dependency is present in the context.
@toolbox.tool("Get personalized settings", available_when=provided(UserInfo))
def get_settings() -> str:
    return "settings"


# Hidden unless a UserInfo is present AND satisfies the predicate. `~`, `&`
# and `|` combine ToolAvailability instances, e.g. `requires(...) & provided(...)`.
@toolbox.tool(
    "Delete a user account (admin only)",
    available_when=requires(UserInfo, predicate=lambda user: user.is_admin),
)
def delete_account() -> str:
    return "account deleted"


def tool_names(context: ToolContext | None = None) -> list[str]:
    return [schema.name for schema in toolbox.get_schema(context=context)]


async def main() -> None:
    # The registry context set at construction time.
    print("regular user:", tool_names())

    # A per-call context overrides it without mutating the registry.
    print("no context:", tool_names(ToolContext()))
    print("admin:", tool_names(ToolContext(UserInfo(name="Mathis", is_admin=True))))


if __name__ == "__main__":
    asyncio.run(main())
