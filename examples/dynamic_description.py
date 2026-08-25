import asyncio
from dataclasses import dataclass

from agenttoolkit import ToolContext, Tools, description_from_context


@dataclass
class Project:
    name: str


tools = Tools()


# The description sent to the LLM changes depending on what's in the
# ToolContext at schema-generation time, with a static fallback if absent.
@tools.tool(
    description_from_context(
        Project,
        render=lambda project: f"Create a new issue in project '{project.name}'",
        fallback="Create a new issue (no project selected)",
    )
)
def create_issue(title: str) -> str:
    return f"issue created: {title}"


async def main() -> None:
    print(tools.get_schema()[0].description)

    context = ToolContext(Project(name="agenttoolkit"))
    print(tools.get_schema(context=context)[0].description)


if __name__ == "__main__":
    asyncio.run(main())
