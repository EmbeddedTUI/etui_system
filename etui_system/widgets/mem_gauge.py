# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmicroLLC

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget


_BAR_WIDTH = 30
_FILLED = "█"
_EMPTY  = "░"


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _bar(used: int, total: int, width: int = _BAR_WIDTH) -> str:
    pct = used / total if total else 0.0
    filled = round(pct * width)
    filled = max(0, min(width, filled))
    if pct >= 0.9:
        colour = "red"
    elif pct >= 0.7:
        colour = "yellow"
    else:
        colour = "green"
    return f"[{colour}]{_FILLED * filled}[/{colour}]{_EMPTY * (width - filled)}"


class MemGauge(Widget):
    """Shows memory and swap usage bars."""

    DEFAULT_CSS = """
    MemGauge {
        height: auto;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="mem-gauge-text")

    def update(self, mem_used: int, mem_total: int, swap_used: int, swap_total: int) -> None:
        mem_bar  = _bar(mem_used,  mem_total)
        swap_bar = _bar(swap_used, swap_total) if swap_total else _EMPTY * _BAR_WIDTH
        text = (
            f"[bold]Mem [/bold] [{mem_bar}]  {_human(mem_used)} / {_human(mem_total)}\n"
            f"[bold]Swap[/bold] [{swap_bar}]  {_human(swap_used)} / {_human(swap_total)}"
        )
        try:
            self.query_one("#mem-gauge-text", Static).update(text)
        except Exception:
            pass
