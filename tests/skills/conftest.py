from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def make_skill() -> Callable[..., Path]:
    """Create a valid skill tree, with optional source overrides for edge tests."""

    def factory(
        root: Path,
        name: str = "internet-research",
        *,
        description: str = "Research current sources.",
        source: str | None = None,
    ) -> Path:
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            source
            or (
                "---\n"
                f"name: {name}\n"
                f"description: {description}\n"
                "license: Apache-2.0\n"
                "metadata:\n"
                "  author: test\n"
                '  version: "1.0"\n'
                "---\n"
                "# Research\n\nUse the bundled workflow.\n"
            ),
            encoding="utf-8",
        )
        return directory

    return factory
