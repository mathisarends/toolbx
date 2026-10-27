from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutputBudget:
    """Trims tool output to something a model can absorb, keeping both ends.

    A tool applies it to text it is about to return; nothing in the library
    applies it on its own.

    `max_line_chars` exists because a line-based budget alone is no protection
    against minified JSON or a base64 blob, where a single line carries the
    entire payload.
    """

    head_lines: int = 60
    tail_lines: int = 40
    max_line_chars: int = 2000

    def __post_init__(self) -> None:
        for name in ("head_lines", "tail_lines", "max_line_chars"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    def shape(self, text: str, *, hint: str | None = None) -> str:
        if not text:
            return text

        lines = [self._clamp(line) for line in text.splitlines()]
        kept = self.head_lines + self.tail_lines
        if len(lines) <= kept:
            return "\n".join(lines)

        omitted = len(lines) - kept
        marker = f"[... {omitted} lines omitted"
        if hint:
            marker = f"{marker}; {hint}"
        return "\n".join(
            [
                *lines[: self.head_lines],
                f"{marker} ...]",
                *lines[-self.tail_lines :],
            ]
        )

    def _clamp(self, line: str) -> str:
        if len(line) <= self.max_line_chars:
            return line
        dropped = len(line) - self.max_line_chars
        return f"{line[: self.max_line_chars]}[... +{dropped} chars ...]"
