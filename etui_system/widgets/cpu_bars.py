# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmicroLLC

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Horizontal
from textual.widget import Widget


_BAR_WIDTH = 20
_FILLED = "█"
_EMPTY  = "░"


def _bar(pct: float, width: int = _BAR_WIDTH) -> str:
    filled = round(pct / 100 * width)
    filled = max(0, min(width, filled))
    if pct >= 90:
        colour = "red"
    elif pct >= 60:
        colour = "yellow"
    else:
        colour = "green"
    return f"[{colour}]{_FILLED * filled}[/{colour}]{_EMPTY * (width - filled)}"


class CpuBars(Widget):
    """Renders one compact bar per logical CPU core."""

    DEFAULT_CSS = """
    CpuBars {
        height: auto;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._percents: list[float] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="cpu-bars-text")

    def update(self, cpu_percent: list[float] | tuple[float, ...]) -> None:
        self._percents = list(cpu_percent)
        self._render_bars()

    def _render_bars(self) -> None:
        if not self._percents:
            return
        parts = []
        for i, pct in enumerate(self._percents):
            parts.append(f"[bold]CPU{i}[/bold] [{_bar(pct)}] {pct:5.1f}%")
        # Two columns if many cores
        if len(parts) > 4:
            mid = (len(parts) + 1) // 2
            lines = []
            for a, b in zip(parts[:mid], parts[mid:] + [""]):
                lines.append(f"{a}   {b}")
            text = "\n".join(lines)
        else:
            text = "\n".join(parts)
        try:
            self.query_one("#cpu-bars-text", Static).update(text)
        except Exception:
            pass
