# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from typing import Any

import psutil

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Label, Static

from etui.plugin import BusMixin, CancelOnLeaveMixin, SettingsField, SettingsSchema

from .bus_contract import (
    PermissionDenied,
    ProcessKilled,
    ProcessNotFound,
    SVC_SYSTEM_KILL,
    SVC_SYSTEM_METRICS,
    SVC_SYSTEM_PROCESS_INFO,
    SVC_SYSTEM_PROCESS_LIST,
    SVC_SYSTEM_RESUME,
    SVC_SYSTEM_SET_POLL_INTERVAL,
    SVC_SYSTEM_SUSPEND,
    TOPIC_SYSTEM_PROCESS_KILLED,
    TOPIC_SYSTEM_SNAPSHOT,
    SystemSnapshot,
)
from .poller import SystemPoller
from .widgets.cpu_bars import CpuBars
from .widgets.mem_gauge import MemGauge
from .widgets.process_table import ProcessTable


_DEFAULT_POLL = float(os.environ.get("ETUI_SYSTEM_POLL", "2"))
_SORT_CYCLE = ["cpu", "mem", "pid", "name", "user"]

_SIGNALS = [
    ("SIGTERM", signal.SIGTERM),
    ("SIGKILL", signal.SIGKILL),
    ("SIGSTOP", signal.SIGSTOP),
    ("SIGCONT", signal.SIGCONT),
    ("SIGHUP",  signal.SIGHUP),
    ("SIGUSR1", signal.SIGUSR1),
    ("SIGUSR2", signal.SIGUSR2),
]


# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------

class SignalDialog(ModalScreen):
    """Let the user choose which signal to send to a process."""

    DEFAULT_CSS = """
    SignalDialog { align: center middle; }
    #sig-box {
        background: $surface;
        border: thick $accent;
        padding: 1 2;
        width: 44;
        height: auto;
    }
    #sig-box Label { margin-bottom: 1; }
    #sig-buttons { height: auto; }
    #sig-buttons Button { width: 1fr; margin: 0 0 1 0; }
    #sig-cancel { margin-top: 1; width: 1fr; }
    """

    def __init__(self, pid: int, name: str) -> None:
        super().__init__()
        self._pid = pid
        self._name = name

    def compose(self) -> ComposeResult:
        with Vertical(id="sig-box"):
            yield Label(f"Send signal to PID {self._pid} ({self._name})")
            with Vertical(id="sig-buttons"):
                for label, sig in _SIGNALS:
                    yield Button(label, id=f"sig-{sig}")
            yield Button("Cancel", id="sig-cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id or ""
        if bid == "sig-cancel":
            self.dismiss(None)
        elif bid.startswith("sig-"):
            try:
                self.dismiss(int(bid[4:]))
            except ValueError:
                self.dismiss(None)


class ProcessDetail(ModalScreen):
    """Show detailed info about a single process."""

    DEFAULT_CSS = """
    ProcessDetail { align: center middle; }
    #pd-box {
        background: $surface;
        border: thick $accent;
        padding: 1 2;
        width: 80;
        height: 30;
    }
    #pd-scroll { height: 1fr; }
    #pd-close { margin-top: 1; }
    """

    def __init__(self, pid: int) -> None:
        super().__init__()
        self._pid = pid

    def compose(self) -> ComposeResult:
        with Vertical(id="pd-box"):
            yield Static("", id="pd-content")
            with ScrollableContainer(id="pd-scroll"):
                pass
            yield Button("Close", id="pd-close")

    def on_mount(self) -> None:
        self.query_one("#pd-content", Static).update(self._build_text())

    def _build_text(self) -> str:
        try:
            p = psutil.Process(self._pid)
            with p.oneshot():
                lines = [
                    f"[bold]PID:[/bold]       {p.pid}",
                    f"[bold]Name:[/bold]      {p.name()}",
                    f"[bold]Status:[/bold]    {p.status()}",
                    f"[bold]User:[/bold]      {p.username()}",
                    f"[bold]CPU%:[/bold]      {p.cpu_percent()}",
                    f"[bold]Mem RSS:[/bold]   {p.memory_info().rss:,} bytes",
                    f"[bold]Threads:[/bold]   {p.num_threads()}",
                    f"[bold]Created:[/bold]   {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(p.create_time()))}",
                ]
                try:
                    lines.append(f"[bold]Cmdline:[/bold]   {' '.join(p.cmdline())}")
                except psutil.AccessDenied:
                    pass
                try:
                    lines.append(f"[bold]CWD:[/bold]       {p.cwd()}")
                except psutil.AccessDenied:
                    pass
                try:
                    fds = p.num_fds()
                    lines.append(f"[bold]Open FDs:[/bold]  {fds}")
                except (psutil.AccessDenied, AttributeError):
                    pass
                try:
                    limits = p.rlimit(psutil.RLIMIT_NOFILE)
                    lines.append(f"[bold]FD limit:[/bold]  {limits[1]}")
                except (AttributeError, psutil.AccessDenied):
                    pass
            return "\n".join(lines)
        except psutil.NoSuchProcess:
            return f"[red]Process {self._pid} no longer exists.[/red]"
        except Exception as exc:
            return f"[red]Error: {exc}[/red]"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Main tab
# ---------------------------------------------------------------------------

class SystemTab(CancelOnLeaveMixin, BusMixin, Vertical):

    BINDINGS = [
        Binding("f5,r", "refresh_now",   "Refresh",  show=True),
        Binding("f9,k", "kill_selected", "Signal",   show=True),
        Binding("f3,/", "focus_filter",  "Filter",   show=True),
        Binding("f4,s", "cycle_sort",    "Sort",     show=True),
        Binding("t",    "toggle_tree",   "Tree",     show=True),
        Binding("enter","show_detail",   "Detail",   show=True),
        Binding("u",    "filter_user",   "My procs", show=True),
    ]

    settings_schema = SettingsSchema(
        section="system",
        fields=(
            SettingsField(key="poll_interval",  type="int",    label="Poll interval (s):",    default=2,     min=1,  max=60),
            SettingsField(key="max_processes",  type="int",    label="Max process rows:",     default=100,   min=10, max=500),
            SettingsField(key="default_sort",   type="choice", label="Default sort column:",  default="cpu",
                          choices=["cpu", "mem", "pid", "name", "user"]),
            SettingsField(key="tree_view",      type="bool",   label="Tree view by default:", default=False),
            SettingsField(key="show_threads",   type="bool",   label="Show threads:",         default=False),
            SettingsField(key="cpu_bar_height", type="int",    label="CPU bar height:",       default=1,     min=1,  max=4),
            SettingsField(key="highlight_user", type="str",    label="Highlight user:",       default=""),
        ),
    )

    DEFAULT_CSS = """
    SystemTab { height: 1fr; }
    SystemTab #sys-toolbar {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $accent;
        align: left middle;
    }
    SystemTab #sys-toolbar Label { margin-right: 1; margin-top: 1; }
    SystemTab #filter-input { width: 24; margin-right: 2; }
    SystemTab #sort-label { margin-right: 1; }
    SystemTab #sys-toolbar Button { margin-right: 1; min-width: 10; }
    SystemTab #sys-process-area { height: 1fr; }
    SystemTab #sys-status {
        height: 1;
        background: $surface;
        padding: 0 1;
        border-top: solid $accent;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._poll_interval: float = _DEFAULT_POLL
        self._max_procs: int = 100
        self._sort_col: str = "cpu"
        self._tree_view: bool = False
        self._show_threads: bool = False
        self._last_snapshot: SystemSnapshot | None = None
        self._poller: SystemPoller | None = None
        self._disposers: list = []

    def survives_leave(self) -> bool:
        return True

    def apply_settings(self, values: dict) -> None:
        env_poll = os.environ.get("ETUI_SYSTEM_POLL")
        self._poll_interval = float(env_poll) if env_poll else float(values.get("poll_interval", self._poll_interval))
        self._max_procs     = int(values.get("max_processes",  self._max_procs))
        self._sort_col      = values.get("default_sort",       self._sort_col)
        self._tree_view     = bool(values.get("tree_view",     self._tree_view))
        self._show_threads  = bool(values.get("show_threads",  self._show_threads))
        if self._poller:
            self._poller.set_interval(self._poll_interval)

    def compose(self) -> ComposeResult:
        yield CpuBars()
        yield MemGauge()
        with Horizontal(id="sys-toolbar"):
            yield Label("Filter:")
            yield Input(placeholder="name / user / PID…", id="filter-input")
            yield Label("Sort:", id="sort-label")
            yield Button("cpu ▼", id="btn-sort", variant="default")
            yield Button("Tree", id="btn-tree", variant="default")
            yield Button("F5 Refresh", id="btn-refresh")
        yield ProcessTable(sort_col=self._sort_col, tree_mode=self._tree_view)
        yield Static("", id="sys-status")

    def on_mount(self) -> None:
        if self.bus is not None:
            self._disposers = [
                self.bus.provide(SVC_SYSTEM_METRICS,           self._svc_metrics),
                self.bus.provide(SVC_SYSTEM_PROCESS_LIST,      self._svc_process_list),
                self.bus.provide(SVC_SYSTEM_PROCESS_INFO,      self._svc_process_info),
                self.bus.provide(SVC_SYSTEM_KILL,              self._svc_kill),
                self.bus.provide(SVC_SYSTEM_SUSPEND,           self._svc_suspend),
                self.bus.provide(SVC_SYSTEM_RESUME,            self._svc_resume),
                self.bus.provide(SVC_SYSTEM_SET_POLL_INTERVAL, self._svc_set_poll_interval),
            ]
        self._poller = SystemPoller(
            interval=self._poll_interval,
            on_snapshot=lambda s: self.app.call_from_thread(self._on_snapshot, s),
        )
        self._poller.start()

    def on_unmount(self) -> None:
        if self._poller:
            self._poller.stop()
        for dispose in self._disposers:
            dispose()

    # -----------------------------------------------------------------------
    # Bus service implementations
    # -----------------------------------------------------------------------

    def _svc_metrics(self) -> dict:
        s = self._last_snapshot
        if s is None:
            return {}
        return {
            "cpu_percent": list(s.cpu_percent),
            "mem_used":    s.mem_used,
            "mem_total":   s.mem_total,
            "swap_used":   s.swap_used,
            "swap_total":  s.swap_total,
            "load_avg":    list(s.load_avg),
        }

    def _svc_process_list(self, *, sort: str = "cpu", limit: int = 50) -> list[dict]:
        s = self._last_snapshot
        if s is None:
            return []
        from .widgets.process_table import _SORT_KEYS
        key_fn = _SORT_KEYS.get(sort, _SORT_KEYS["cpu"])
        procs = sorted(s.top_procs, key=key_fn, reverse=True)
        return list(procs[:limit])

    def _svc_process_info(self, pid: int) -> dict:
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                info: dict[str, Any] = {
                    "pid":      p.pid,
                    "name":     p.name(),
                    "status":   p.status(),
                    "user":     p.username(),
                    "cpu":      p.cpu_percent(),
                    "mem_rss":  p.memory_info().rss,
                    "threads":  p.num_threads(),
                    "created":  p.create_time(),
                }
                try:
                    info["cmdline"] = p.cmdline()
                except psutil.AccessDenied:
                    info["cmdline"] = []
                try:
                    info["cwd"] = p.cwd()
                except psutil.AccessDenied:
                    info["cwd"] = ""
                try:
                    info["fds"] = p.num_fds()
                except (psutil.AccessDenied, AttributeError):
                    info["fds"] = -1
            return info
        except psutil.NoSuchProcess:
            raise ProcessNotFound(pid)

    def _svc_kill(self, pid: int, sig: int = 15) -> None:
        try:
            psutil.Process(pid).send_signal(sig)
        except psutil.NoSuchProcess:
            raise ProcessNotFound(pid)
        except psutil.AccessDenied:
            raise PermissionDenied(pid, sig)

    def _svc_suspend(self, pid: int) -> None:
        self._svc_kill(pid, signal.SIGSTOP)

    def _svc_resume(self, pid: int) -> None:
        self._svc_kill(pid, signal.SIGCONT)

    def _svc_set_poll_interval(self, seconds: float) -> None:
        self._poll_interval = max(0.5, float(seconds))
        if self._poller:
            self._poller.set_interval(self._poll_interval)

    # -----------------------------------------------------------------------
    # Snapshot callback (called from poller thread via call_from_thread)
    # -----------------------------------------------------------------------

    def _on_snapshot(self, snapshot: SystemSnapshot) -> None:
        self._last_snapshot = snapshot
        try:
            self.query_one(CpuBars).update(list(snapshot.cpu_percent))
            self.query_one(MemGauge).update(
                snapshot.mem_used, snapshot.mem_total,
                snapshot.swap_used, snapshot.swap_total,
            )
            procs = list(snapshot.top_procs)[:self._max_procs]
            self.query_one(ProcessTable).refresh_rows(procs)
            la = snapshot.load_avg
            self.query_one("#sys-status", Static).update(
                f"Load avg: {la[0]:.2f}  {la[1]:.2f}  {la[2]:.2f}  "
                f"| Procs: {len(snapshot.top_procs)}"
            )
        except Exception:
            pass
        if self.bus is not None:
            self.bus.emit(TOPIC_SYSTEM_SNAPSHOT, snapshot)

    # -----------------------------------------------------------------------
    # UI event handlers
    # -----------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            try:
                self.query_one(ProcessTable).filter_text = event.value
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "btn-refresh":
            self.action_refresh_now()
        elif bid == "btn-sort":
            self.action_cycle_sort()
        elif bid == "btn-tree":
            self.action_toggle_tree()

    # -----------------------------------------------------------------------
    # Bindings / actions
    # -----------------------------------------------------------------------

    def action_refresh_now(self) -> None:
        if self._poller:
            self.run_worker(self._force_refresh, thread=True)

    def _force_refresh(self) -> None:
        from .poller import _collect_snapshot
        try:
            snapshot = _collect_snapshot(self._poll_interval)
            self.app.call_from_thread(self._on_snapshot, snapshot)
        except Exception:
            pass

    def action_kill_selected(self) -> None:
        pid = self._get_selected_pid()
        if pid is None:
            return
        name = self._proc_name(pid)
        self.run_worker(self._do_kill_dialog(pid, name))

    async def _do_kill_dialog(self, pid: int, name: str) -> None:
        sig = await self.app.push_screen_wait(SignalDialog(pid, name))
        if sig is None:
            return
        try:
            self._svc_kill(pid, sig)
            if self.bus is not None:
                self.bus.emit(TOPIC_SYSTEM_PROCESS_KILLED, ProcessKilled(pid, sig, name))
            self.app.notify(f"Sent signal {sig} to {name} ({pid})")
            self.action_refresh_now()
        except ProcessNotFound:
            self.app.notify(f"Process {pid} no longer exists", severity="warning")
        except PermissionDenied:
            self.app.notify(f"Permission denied: cannot signal {name} ({pid})", severity="error")

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#filter-input", Input).focus()
        except Exception:
            pass

    def action_cycle_sort(self) -> None:
        try:
            idx = _SORT_CYCLE.index(self._sort_col)
        except ValueError:
            idx = 0
        self._sort_col = _SORT_CYCLE[(idx + 1) % len(_SORT_CYCLE)]
        try:
            tbl = self.query_one(ProcessTable)
            tbl.sort_col = self._sort_col
            self.query_one("#btn-sort", Button).label = f"{self._sort_col} ▼"
        except Exception:
            pass

    def action_toggle_tree(self) -> None:
        self._tree_view = not self._tree_view
        try:
            tbl = self.query_one(ProcessTable)
            tbl.tree_mode = self._tree_view
            btn = self.query_one("#btn-tree", Button)
            btn.variant = "primary" if self._tree_view else "default"
        except Exception:
            pass

    def action_show_detail(self) -> None:
        pid = self._get_selected_pid()
        if pid is None:
            return
        self.run_worker(self._do_show_detail(pid))

    async def _do_show_detail(self, pid: int) -> None:
        await self.app.push_screen_wait(ProcessDetail(pid))

    def action_filter_user(self) -> None:
        try:
            inp = self.query_one("#filter-input", Input)
            if inp.value:
                inp.value = ""
            else:
                inp.value = os.environ.get("USER", "")
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _get_selected_pid(self) -> int | None:
        try:
            return self.query_one(ProcessTable).selected_pid()
        except Exception:
            return None

    def _proc_name(self, pid: int) -> str:
        try:
            return psutil.Process(pid).name()
        except Exception:
            return str(pid)
