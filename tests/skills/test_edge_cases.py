import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from agenttoolkit import Skills, parse_skill


def skill_source(
    *,
    name: str = "internet-research",
    description: str = "Research current sources.",
    instructions: str = "# Research\n\nFollow the workflow.",
    extra: str = "",
) -> str:
    return (
        f"---\nname: {name}\ndescription: {description}\n{extra}---\n{instructions}\n"
    )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("# Missing frontmatter", "must start with YAML frontmatter"),
        ("---\n- item\n---\nBody\n", "frontmatter must be a mapping"),
        ("---\nname: [broken\n---\nBody\n", "invalid YAML frontmatter"),
        (
            "---\ndescription: Useful.\n---\nBody\n",
            "requires a non-empty string 'name'",
        ),
        (
            "---\nname: internet-research\n---\nBody\n",
            "requires a non-empty string 'description'",
        ),
        (
            skill_source(name="internet-research", instructions=" \n"),
            "must contain Markdown instructions",
        ),
        (
            skill_source(extra="license: 42\n"),
            "field 'license' must be a non-empty string",
        ),
        (
            skill_source(extra="metadata:\n  version: 1\n"),
            "field 'metadata' must map strings to strings",
        ),
    ],
)
def test_invalid_skill_documents_have_actionable_errors(
    tmp_path: Path,
    source: str,
    message: str,
    make_skill: Callable[..., Path],
) -> None:
    skill_file = make_skill(tmp_path, source=source) / "SKILL.md"

    with pytest.raises(ValueError, match=message):
        parse_skill(skill_file)


@pytest.mark.parametrize("name", ["Uppercase", "trailing-", "a" * 65])
def test_skill_names_follow_portable_directory_rules(
    tmp_path: Path,
    name: str,
    make_skill: Callable[..., Path],
) -> None:
    skill_file = make_skill(tmp_path, name=name) / "SKILL.md"

    with pytest.raises(ValueError, match="must be 1-64 lowercase"):
        parse_skill(skill_file)


def test_skill_name_must_match_its_directory(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    skill_file = (
        make_skill(
            tmp_path,
            name="directory-name",
            source=skill_source(name="different-name"),
        )
        / "SKILL.md"
    )

    with pytest.raises(ValueError, match="must match its parent directory"):
        parse_skill(skill_file)


def test_skill_text_fields_enforce_documented_limits(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    too_long_description = skill_source(description="x" * 1025)
    description_file = (
        make_skill(
            tmp_path / "description",
            source=too_long_description,
        )
        / "SKILL.md"
    )
    too_long_compatibility = skill_source(extra=f"compatibility: {'x' * 501}\n")
    compatibility_file = (
        make_skill(
            tmp_path / "compatibility",
            source=too_long_compatibility,
        )
        / "SKILL.md"
    )

    with pytest.raises(ValueError, match="description must be at most 1024"):
        parse_skill(description_file)
    with pytest.raises(ValueError, match="compatibility must be at most 500"):
        parse_skill(compatibility_file)


def test_missing_skill_file_is_reported_as_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Could not read skill file"):
        parse_skill(tmp_path / "missing" / "SKILL.md")


def test_skills_reject_empty_missing_and_file_roots(tmp_path: Path) -> None:
    file_root = tmp_path / "file.txt"
    file_root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="At least one"):
        Skills.from_dir()
    with pytest.raises(ValueError, match="does not exist"):
        Skills.from_dir(tmp_path / "missing")
    with pytest.raises(ValueError, match="must be a directory"):
        Skills.from_dir(file_root)


def test_duplicate_skill_uses_later_root_and_logs_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    make_skill: Callable[..., Path],
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    make_skill(first, source=skill_source(description="First description."))
    latest = make_skill(
        second,
        source=skill_source(description="Latest description."),
    )

    with caplog.at_level(logging.WARNING):
        skills = Skills.from_dir(first, second)

    assert skills.get("internet-research").directory == latest.resolve()
    assert skills.directories == (latest.resolve(),)
    assert "overrides skill" in caplog.text


def test_missing_skill_lists_available_names(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    skills = Skills.from_dir(make_skill(tmp_path).parent)

    with pytest.raises(
        ValueError,
        match=r"not found\. Available skills: internet-research",
    ):
        skills.get("missing")


def test_load_refreshes_instructions_from_disk(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path)
    skills = Skills.from_dir(tmp_path)
    (directory / "SKILL.md").write_text(
        skill_source(instructions="# Research\n\nUse the updated workflow."),
        encoding="utf-8",
    )

    loaded = skills.load("internet-research")

    assert loaded.instructions.endswith("Use the updated workflow.")


def test_load_rejects_skill_renamed_after_discovery(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path)
    skills = Skills.from_dir(tmp_path)
    (directory / "SKILL.md").write_text(
        skill_source(name="different-name"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must match its parent directory"):
        skills.load("internet-research")


def test_refresh_keeps_previous_registry_when_discovery_fails(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    make_skill(tmp_path)
    skills = Skills.from_dir(tmp_path)
    make_skill(tmp_path, name="broken", source="# Missing frontmatter")

    with pytest.raises(ValueError, match="must start with YAML frontmatter"):
        skills.refresh()

    assert skills.names() == ["internet-research"]
