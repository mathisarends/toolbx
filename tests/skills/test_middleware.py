import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from agenttoolkit import (
    CallLoggingMiddleware,
    ErrorBoundaryMiddleware,
    SkillRefreshMiddleware,
    Skills,
    ToolContext,
    Tools,
)


@pytest.mark.asyncio
async def test_writing_tool_refreshes_and_returns_new_catalog(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    make_skill(tmp_path, "existing")
    skills = Skills.from_dir(tmp_path)
    tools = Tools(
        context=ToolContext(skills),
        middleware=[SkillRefreshMiddleware()],
    )

    @tools.action("Write a skill")
    def write_skill() -> str:
        make_skill(tmp_path, "created")
        return "written"

    result = await tools.execute("write_skill")

    assert result == "written"
    assert skills.names() == ["created", "existing"]
    assert skills.revision == 1


@pytest.mark.asyncio
async def test_every_tool_refreshes_registry_by_default(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    make_skill(tmp_path, "existing")
    skills = Skills.from_dir(tmp_path)
    tools = Tools(
        context=ToolContext(skills),
        middleware=[SkillRefreshMiddleware()],
    )

    @tools.action("Write without declaring the effect")
    def other_tool() -> str:
        make_skill(tmp_path, "created")
        return "written"

    result = await tools.execute("other_tool")

    assert result == "written"
    assert skills.names() == ["created", "existing"]


@pytest.mark.asyncio
async def test_invalid_edit_reports_error_and_keeps_active_registry(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path, "existing")
    skills = Skills.from_dir(tmp_path)
    tools = Tools(
        context=ToolContext(skills),
        middleware=[SkillRefreshMiddleware()],
    )

    @tools.action("Write an invalid skill")
    def write_skill() -> str:
        (directory / "SKILL.md").write_text(
            "# Missing frontmatter",
            encoding="utf-8",
        )
        return "written"

    with caplog.at_level(logging.ERROR):
        result = await tools.execute("write_skill")

    assert result == "written"
    assert skills.names() == ["existing"]
    assert skills.revision == 0
    assert "Skill refresh failed after tool 'write_skill'" in caplog.text
    assert "must start with YAML frontmatter" in caplog.text


@pytest.mark.asyncio
async def test_failed_writing_tool_still_reports_catalog_update(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    make_skill(tmp_path, "existing")
    skills = Skills.from_dir(tmp_path)
    tools = Tools(
        context=ToolContext(skills),
        middleware=(
            ErrorBoundaryMiddleware(),
            CallLoggingMiddleware(),
            SkillRefreshMiddleware(),
        ),
    )

    @tools.action("Write and fail")
    def write_skill() -> None:
        make_skill(tmp_path, "created")
        raise RuntimeError("command failed")

    result = await tools.execute("write_skill")

    assert result == "Tool failed: command failed"
    assert skills.names() == ["created", "existing"]


@pytest.mark.asyncio
async def test_context_without_skills_makes_the_middleware_a_no_op() -> None:
    tools = Tools(middleware=[SkillRefreshMiddleware()])

    @tools.action("Write something")
    def write_file() -> str:
        return "written"

    assert await tools.execute("write_file") == "written"


@pytest.mark.asyncio
async def test_per_call_context_selects_the_refreshed_registry(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    make_skill(first_root, "existing")
    make_skill(second_root, "existing")
    first = Skills.from_dir(first_root)
    second = Skills.from_dir(second_root)
    tools = Tools(
        context=ToolContext(first),
        middleware=[SkillRefreshMiddleware()],
    )

    @tools.action("Write a skill")
    def write_skill() -> str:
        make_skill(first_root, "created-in-first")
        make_skill(second_root, "created-in-second")
        return "written"

    await tools.execute("write_skill", context=ToolContext(second))

    assert second.names() == ["created-in-second", "existing"]
    assert first.names() == ["existing"]
