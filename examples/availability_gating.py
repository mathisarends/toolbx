import asyncio
from dataclasses import dataclass

from toolbox import Toolbox, ToolContext, provided, requires


@dataclass
class UserInfo:
    name: str
    is_admin: bool = False


toolbox = Toolbox(context=ToolContext(UserInfo(name="Mathis")))


has_user = provided(UserInfo)
is_admin = requires(UserInfo, predicate=lambda user: user.is_admin)


@toolbox.tool("Get personalized settings", available_when=has_user)
def get_settings() -> str:
    return "settings"


# `~`, `&` and `|` combine availabilities, e.g. `has_user & ~is_admin`.
@toolbox.tool("Delete a user account (admin only)", available_when=is_admin)
def delete_account() -> str:
    return "account deleted"


def tool_names(context: ToolContext | None = None) -> list[str]:
    return [schema.name for schema in toolbox.schemas(context=context)]


async def main() -> None:
    # The registry context set at construction time.
    print("regular user:", tool_names())

    # A per-call context overrides it without mutating the registry.
    print("no context:", tool_names(ToolContext()))
    print("admin:", tool_names(ToolContext(UserInfo(name="Mathis", is_admin=True))))


if __name__ == "__main__":
    asyncio.run(main())
