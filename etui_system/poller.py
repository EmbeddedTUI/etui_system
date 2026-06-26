# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations

import threading
import time
from typing import Callable

import psutil

from .bus_contract import PollError, SystemSnapshot

_PROC_ATTRS = [
    "pid", "name", "username", "cpu_percent", "memory_info",
    "memory_percent", "status", "cmdline",
]

_TOP_N = 20


def _collect_snapshot(interval: float) -> SystemSnapshot:
    """Gather one system snapshot; *interval* is the CPU measurement window."""
    try:
        cpu = tuple(psutil.cpu_percent(percpu=True))
        mem = psutil.virtual_memory()
        swp = psutil.swap_memory()
        try:
            load = tuple(psutil.getloadavg())
        except AttributeError:
            load = (0.0, 0.0, 0.0)

        procs = []
        for p in psutil.process_iter(_PROC_ATTRS):
            try:
                info = p.info
                cmdline = info.get("cmdline") or []
                mem_info = info.get("memory_info")
                procs.append({
                    "pid":      info["pid"],
                    "name":     info.get("name") or "",
                    "user":     info.get("username") or "",
                    "cpu":      info.get("cpu_percent") or 0.0,
                    "mem_pct":  info.get("memory_percent") or 0.0,
                    "rss":      mem_info.rss if mem_info else 0,
                    "vms":      mem_info.vms if mem_info else 0,
                    "status":   info.get("status") or "?",
                    "cmd":      " ".join(cmdline) if cmdline else (info.get("name") or ""),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        top = sorted(procs, key=lambda p: p["cpu"], reverse=True)[:_TOP_N]

        return SystemSnapshot(
            cpu_percent=cpu,
            mem_used=mem.used,
            mem_total=mem.total,
            swap_used=swp.used,
            swap_total=swp.total,
            load_avg=load,
            top_procs=tuple(top),
        )
    except Exception as exc:
        raise PollError(str(exc)) from exc


class SystemPoller:
    """Background thread that collects system metrics and calls *on_snapshot*."""

    def __init__(self, interval: float, on_snapshot: Callable[[SystemSnapshot], None]) -> None:
        self._interval = interval
        self._on_snapshot = on_snapshot
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def interval(self) -> float:
        return self._interval

    def set_interval(self, seconds: float) -> None:
        self._interval = max(0.5, float(seconds))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="etui-system-poller")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _run(self) -> None:
        # Prime the CPU measurement (first call always returns 0.0).
        try:
            psutil.cpu_percent(percpu=True)
        except Exception:
            pass
        while not self._stop.wait(self._interval):
            try:
                snapshot = _collect_snapshot(self._interval)
                self._on_snapshot(snapshot)
            except PollError:
                pass
