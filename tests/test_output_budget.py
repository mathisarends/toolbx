import pytest

from toolbox import OutputBudget


def test_short_output_passes_through_unchanged() -> None:
    budget = OutputBudget(head_lines=3, tail_lines=2)
    text = "a\nb\nc"

    assert budget.shape(text) == text
    assert budget.shape("") == ""


def test_long_output_keeps_both_ends_and_reports_the_gap() -> None:
    budget = OutputBudget(head_lines=2, tail_lines=2)
    shaped = budget.shape("\n".join(str(index) for index in range(100)))

    lines = shaped.splitlines()
    assert lines[:2] == ["0", "1"]
    assert lines[-2:] == ["98", "99"]
    assert lines[2] == "[... 96 lines omitted ...]"


def test_hint_is_woven_into_the_marker() -> None:
    budget = OutputBudget(head_lines=1, tail_lines=1)
    shaped = budget.shape("a\nb\nc\nd", hint="full output: /tmp/x.log")

    assert "[... 2 lines omitted; full output: /tmp/x.log ...]" in shaped


def test_single_long_line_is_clamped() -> None:
    budget = OutputBudget(max_line_chars=10)
    shaped = budget.shape("x" * 25)

    assert shaped == f"{'x' * 10}[... +15 chars ...]"


@pytest.mark.parametrize("field", ["head_lines", "tail_lines", "max_line_chars"])
def test_budget_fields_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        OutputBudget(**{field: 0})
