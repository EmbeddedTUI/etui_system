# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

from __future__ import annotations
from dataclasses import dataclass, field

# ---- Services ---------------------------------------------------------------
SVC_SYSTEM_METRICS           = "system.metrics"
SVC_SYSTEM_PROCESS_LIST      = "system.process_list"
SVC_SYSTEM_PROCESS_INFO      = "system.process_info"
SVC_SYSTEM_KILL              = "system.kill"
SVC_SYSTEM_SUSPEND           = "system.suspend"
SVC_SYSTEM_RESUME            = "system.resume"
SVC_SYSTEM_SET_POLL_INTERVAL = "system.set_poll_interval"

# ---- Events -----------------------------------------------------------------
TOPIC_SYSTEM_SNAPSHOT        = "system.snapshot"
TOPIC_SYSTEM_PROCESS_KILLED  = "system.process_killed"


# ---- Payload dataclasses ----------------------------------------------------
@dataclass(frozen=True)
class SystemSnapshot:
    cpu_percent: tuple[float, ...]          # per-core utilisation 0–100
    mem_used: int                           # bytes
    mem_total: int                          # bytes
    swap_used: int
    swap_total: int
    load_avg: tuple[float, float, float]    # 1 / 5 / 15 min
    top_procs: tuple[dict, ...]             # top-N by CPU


@dataclass(frozen=True)
class ProcessKilled:
    pid: int
    sig: int
    name: str


# ---- Typed exceptions -------------------------------------------------------
class ProcessNotFound(Exception):
    def __init__(self, pid: int) -> None:
        super().__init__(f"No process with PID {pid}")
        self.pid = pid


class PermissionDenied(Exception):
    def __init__(self, pid: int, sig: int) -> None:
        super().__init__(f"Permission denied sending signal {sig} to PID {pid}")
        self.pid = pid
        self.sig = sig


class PollError(Exception):
    pass
