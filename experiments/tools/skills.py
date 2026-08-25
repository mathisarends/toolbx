from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from agenttoolkit import Skills
from agenttoolkit.tools import Inject, ToolRegistry


class LoadSkillParams(BaseModel):
    name: str = Field(description="Exact skill name from <available_skills>")


def register_skill_loader(
    tools: ToolRegistry,
    *,
    container_root: str | PurePosixPath = "/skills",
) -> None:
    root = PurePosixPath(container_root)

    @tools.register(
        "Load one skill's full instructions, directory, and resource list.",
        name="load_skill",
        params=LoadSkillParams,
    )
    def load_skill(
        params: LoadSkillParams,
        skills: Inject[Skills],
    ) -> dict[str, object]:
        loaded = skills.load(params.name)
        return {
            "name": loaded.name,
            "instructions": loaded.instructions,
            "directory": str(root / loaded.name),
            "resources": list(loaded.resources),
        }
