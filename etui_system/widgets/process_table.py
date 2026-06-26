# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmicroLLC

from __future__ import annotations

from textual.widgets import DataTable
from textual.reactive import reactive


_COLUMNS = [
    ("PID",    6,  "pid"),
    ("USER",   10, "user"),
    ("CPU%",   7,  "cpu"),
    ("MEM%",   7,  "mem_pct"),
    ("RSS",    9,  "rss"),
    ("S",      3,  "status"),
    ("COMMAND", 0, "cmd"),
]

_SORT_KEYS = {
    "cpu":  lambda p: p["cpu"],
    "mem":  lambda p: p["mem_pct"],
    "pid":  lambda p: p["pid"],
    "name": lambda p: p["name"].lower(),
    "user": lambda p: p["user"].lower(),
}


def _human(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n //= 1024
    return f"{n}T"


class ProcessTable(DataTable):
    """Sortable, filterable process table."""

    sort_col: reactive[str] = reactive("cpu")
    tree_mode: reactive[bool] = reactive(False)
    filter_text: reactive[str] = reactive("")

    def __init__(self, sort_col: str = "cpu", tree_mode: bool = False) -> None:
        self._procs: list[dict] = []  # must precede super().__init__ so watchers don't crash
        super().__init__(zebra_stripes=True, cursor_type="row")
        self.sort_col = sort_col
        self.tree_mode = tree_mode

    def on_mount(self) -> None:
        for label, width, _ in _COLUMNS:
            if width:
                self.add_column(label, width=width, key=label)
            else:
                self.add_column(label, key=label)

    def refresh_rows(self, procs: list[dict]) -> None:
        self._procs = procs
        self._redraw()

    def _redraw(self) -> None:
        key_fn = _SORT_KEYS.get(self.sort_col, _SORT_KEYS["cpu"])
        filt = self.filter_text.lower()
        rows = [
            p for p in self._procs
            if not filt or filt in p["name"].lower() or filt in p["user"].lower()
            or filt in str(p["pid"])
        ]
        rows.sort(key=key_fn, reverse=True)

        self.clear()
        for p in rows:
            status_char = (p["status"] or "?")[:1].upper()
            self.add_row(
                str(p["pid"]),
                (p["user"] or "")[:10],
                f"{p['cpu']:.1f}",
                f"{p['mem_pct']:.1f}",
                _human(p["rss"]),
                status_char,
                p["cmd"][:80] or p["name"],
                key=str(p["pid"]),
            )

    def watch_filter_text(self, _: str) -> None:
        self._redraw()

    def watch_sort_col(self, _: str) -> None:
        self._redraw()

    def selected_pid(self) -> int | None:
        """Return the PID of the currently highlighted row, or None."""
        try:
            row = self.get_row_at(self.cursor_row)
            return int(row[0])
        except Exception:
            return None
