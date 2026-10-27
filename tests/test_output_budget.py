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


@pytest.mark.parametrize(
    "field", ["head_lines", "tail_lines", "max_line_chars", "max_chars"]
)
def test_budget_fields_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        OutputBudget(**{field: 0})


@pytest.mark.parametrize("text", ["a\r\nb\r\n", "a\nb\n", "a\rb\r"])
def test_short_output_preserves_line_endings(text: str) -> None:
    assert OutputBudget().shape(text) == text


def test_a_single_excess_line_is_not_replaced_by_a_longer_marker() -> None:
    text = "a\nb\nc\n"
    assert OutputBudget(head_lines=1, tail_lines=1).shape(text) == text


def test_character_budget_preserves_both_ends_and_counts_its_marker() -> None:
    text = "BEGIN" + "x" * 1000 + "END"
    shaped = OutputBudget(max_chars=100).shape(text)
    assert len(shaped) == 100
    assert shaped.startswith("BEGIN")
    assert shaped.endswith("END")
    assert "output truncated" in shaped


@pytest.mark.parametrize("limit", [1, 8, 32, 100])
def test_total_budget_holds_for_long_lines_large_hints_and_tiny_caps(
    limit: int,
) -> None:
    text = "\r\n".join(["x" * 4000] * 1000)
    shaped = OutputBudget(max_chars=limit).shape(text, hint="details:" + "y" * 1000)
    assert len(shaped) <= limit
