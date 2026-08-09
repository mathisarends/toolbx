from collections.abc import Callable
from pathlib import Path

import pytest

from agenttoolkit import (
    LoadedSkill,
    Skills,
    parse_skill,
)


def test_discovers_and_parses_skill_metadata(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path)

    skills = Skills.from_dir(tmp_path)
    skill = parse_skill(directory / "SKILL.md")

    assert len(skills) == 1
    assert skills.names() == ["internet-research"]
    assert skill.metadata == {"author": "test", "version": "1.0"}
    assert skill.license == "Apache-2.0"


def test_progressive_load_lists_resources_without_reading_them(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path)
    references = directory / "references"
    references.mkdir()
    (references / "guide.md").write_text("Loaded later.", encoding="utf-8")

    skills = Skills.from_dir(tmp_path)
    loaded = skills.load("internet-research")

    assert isinstance(loaded, LoadedSkill)
    assert loaded.name == "internet-research"
    assert "Use the bundled workflow" in loaded.instructions
    assert loaded.directory == directory.resolve()
    assert loaded.resources == ("references/guide.md",)
    assert "Loaded later." not in loaded.instructions


def test_render_prompt_contains_only_name_and_description(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    make_skill(tmp_path)

    prompt = Skills.from_dir(tmp_path).render_prompt()

    assert "<name>internet-research</name>" in prompt
    assert "<description>Research current sources.</description>" in prompt
    assert "Use the bundled workflow" not in prompt


def test_empty_skill_registry_renders_an_empty_prompt(tmp_path: Path) -> None:
    skills = Skills.from_dir(tmp_path)

    assert skills.render_prompt() == ""
    assert skills.size == 0
    assert skills.revision == 0
    assert skills.directories == ()


def test_load_describes_binary_resources_without_reading_them(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path)
    (directory / "logo.bin").write_bytes(b"\xff\x00")
    loaded = Skills.from_dir(tmp_path).load("internet-research")

    assert loaded.resources == ("logo.bin",)
    assert loaded.directory / loaded.resources[0] == directory / "logo.bin"


def test_invalid_skill_name_is_rejected(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    make_skill(tmp_path, name="invalid--name")

    with pytest.raises(ValueError, match="without leading"):
        Skills.from_dir(tmp_path)


def test_refresh_registers_new_skills(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    make_skill(tmp_path)
    skills = Skills.from_dir(tmp_path)
    new_directory = make_skill(
        tmp_path,
        name="code-review",
        description="Review code changes.",
    )

    changes = skills.refresh()

    assert skills.names() == ["code-review", "internet-research"]
    assert skills.get("code-review").directory == new_directory.resolve()
    assert changes.revision == 1
    assert changes.added == ("code-review",)
    assert changes.updated == ()
    assert changes.removed == ()


def test_refresh_unregisters_removed_skills(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path)
    skills = Skills.from_dir(tmp_path)
    (directory / "SKILL.md").unlink()
    directory.rmdir()

    changes = skills.refresh_if_changed()

    assert changes.changed
    assert changes.revision == 1
    assert changes.added == ()
    assert changes.updated == ()
    assert changes.removed == ("internet-research",)
    assert skills.names() == []


def test_refresh_rebuilds_registry_from_disk(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path)
    skills = Skills.from_dir(tmp_path)
    (directory / "SKILL.md").write_text(
        (
            "---\n"
            "name: internet-research\n"
            "description: Updated description.\n"
            "---\n"
            "# Research\n\nUse the updated workflow.\n"
        ),
        encoding="utf-8",
    )

    changes = skills.refresh()

    assert skills.get("internet-research").description == "Updated description."
    assert changes.revision == 1
    assert changes.updated == ("internet-research",)


def test_refresh_if_changed_skips_unchanged_documents(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    make_skill(tmp_path)
    skills = Skills.from_dir(tmp_path)

    changes = skills.refresh_if_changed()

    assert not changes.changed
    assert changes.revision == 0


def test_load_exposes_script_path_for_a_general_process_runner(
    tmp_path: Path,
    make_skill: Callable[..., Path],
) -> None:
    directory = make_skill(tmp_path)
    scripts = directory / "scripts"
    scripts.mkdir()
    (scripts / "echo.py").write_text(
        "import sys\nprint('|'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    loaded = Skills.from_dir(tmp_path).load("internet-research")

    assert loaded.resources == ("scripts/echo.py",)
    assert loaded.directory / loaded.resources[0] == scripts / "echo.py"
