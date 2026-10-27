import json
from datetime import date

import pytest
from pydantic import BaseModel

from toolbx import OutputBudget, to_text


def test_short_output_passes_through_unchanged() -> None:
    budget = OutputBudget(head_lines=3, tail_lines=2)
    text = "a\nb\nc"

    assert budget.truncate(text) == text
    assert budget.truncate("") == ""


def test_long_output_keeps_both_ends_and_reports_the_gap() -> None:
    budget = OutputBudget(head_lines=2, tail_lines=2)
    shaped = budget.truncate("\n".join(str(index) for index in range(100)))

    lines = shaped.splitlines()
    assert lines[:2] == ["0", "1"]
    assert lines[-2:] == ["98", "99"]
    assert lines[2] == "[... 96 lines omitted ...]"


def test_hint_is_woven_into_the_marker() -> None:
    budget = OutputBudget(head_lines=1, tail_lines=1)
    shaped = budget.truncate("a\nb\nc\nd", hint="full output: /tmp/x.log")

    assert "[... 2 lines omitted; full output: /tmp/x.log ...]" in shaped


def test_single_long_line_is_clamped() -> None:
    budget = OutputBudget(max_line_chars=10)
    shaped = budget.truncate("x" * 25)

    assert shaped == f"{'x' * 10}[... +15 chars ...]"


@pytest.mark.parametrize(
    "field", ["head_lines", "tail_lines", "max_line_chars", "max_chars"]
)
def test_budget_fields_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        OutputBudget(**{field: 0})


@pytest.mark.parametrize("text", ["a\r\nb\r\n", "a\nb\n", "a\rb\r"])
def test_short_output_preserves_line_endings(text: str) -> None:
    assert OutputBudget().truncate(text) == text


def test_a_single_excess_line_is_not_replaced_by_a_longer_marker() -> None:
    text = "a\nb\nc\n"
    assert OutputBudget(head_lines=1, tail_lines=1).truncate(text) == text


def test_character_budget_preserves_both_ends_and_counts_its_marker() -> None:
    text = "BEGIN" + "x" * 1000 + "END"
    shaped = OutputBudget(max_chars=100).truncate(text)
    assert len(shaped) == 100
    assert shaped.startswith("BEGIN")
    assert shaped.endswith("END")
    assert "output truncated" in shaped


@pytest.mark.parametrize("limit", [1, 8, 32, 100])
def test_total_budget_holds_for_long_lines_large_hints_and_tiny_caps(
    limit: int,
) -> None:
    text = "\r\n".join(["x" * 4000] * 1000)
    shaped = OutputBudget(max_chars=limit).truncate(text, hint="details:" + "y" * 1000)
    assert len(shaped) <= limit


def test_to_text_passes_strings_through_unchanged() -> None:
    assert to_text('Tool failed: "x"') == 'Tool failed: "x"'


def test_to_text_serializes_models_containers_and_unknown_values() -> None:
    class User(BaseModel):
        name: str
        joined: date

    class Opaque:
        def __str__(self) -> str:
            return "opaque"

    assert json.loads(to_text(User(name="Ada", joined=date(2026, 1, 2)))) == {
        "name": "Ada",
        "joined": "2026-01-02",
    }
    assert json.loads(to_text({"items": [1, "ü"], "value": Opaque()})) == {
        "items": [1, "ü"],
        "value": "opaque",
    }
    assert to_text(None) == "null"
