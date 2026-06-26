# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmicio LLC

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from etui_system.bus_contract import PollError, SystemSnapshot
from etui_system.poller import SystemPoller, _collect_snapshot


def _fake_cpu(percpu=False):
    return [10.0, 20.0] if percpu else 15.0


def _fake_vmem():
    m = MagicMock()
    m.used = 4 * 1024 ** 3
    m.total = 16 * 1024 ** 3
    return m


def _fake_swap():
    m = MagicMock()
    m.used = 0
    m.total = 4 * 1024 ** 3
    return m


def _fake_proc(pid=1, name="test", user="root", cpu=5.0, mem=1.0):
    p = MagicMock()
    p.info = {
        "pid": pid, "name": name, "username": user,
        "cpu_percent": cpu, "memory_percent": mem,
        "memory_info": MagicMock(rss=1024 * 1024, vms=2 * 1024 * 1024),
        "status": "running", "cmdline": [name],
    }
    return p


class CollectSnapshotTests(unittest.TestCase):
    @patch("etui_system.poller.psutil.process_iter", return_value=[_fake_proc()])
    @patch("etui_system.poller.psutil.getloadavg", return_value=(0.5, 0.4, 0.3))
    @patch("etui_system.poller.psutil.swap_memory", side_effect=_fake_swap)
    @patch("etui_system.poller.psutil.virtual_memory", side_effect=_fake_vmem)
    @patch("etui_system.poller.psutil.cpu_percent", side_effect=_fake_cpu)
    def test_returns_snapshot(self, *_):
        s = _collect_snapshot(2.0)
        self.assertIsInstance(s, SystemSnapshot)
        self.assertEqual(s.cpu_percent, (10.0, 20.0))
        self.assertEqual(s.mem_total, 16 * 1024 ** 3)
        self.assertEqual(len(s.top_procs), 1)
        self.assertEqual(s.top_procs[0]["name"], "test")

    @patch("etui_system.poller.psutil.process_iter", return_value=[_fake_proc()])
    @patch("etui_system.poller.psutil.getloadavg", side_effect=AttributeError)
    @patch("etui_system.poller.psutil.swap_memory", side_effect=_fake_swap)
    @patch("etui_system.poller.psutil.virtual_memory", side_effect=_fake_vmem)
    @patch("etui_system.poller.psutil.cpu_percent", side_effect=_fake_cpu)
    def test_load_avg_fallback_when_unavailable(self, *_):
        s = _collect_snapshot(2.0)
        self.assertEqual(s.load_avg, (0.0, 0.0, 0.0))

    @patch("etui_system.poller.psutil.cpu_percent", side_effect=RuntimeError("boom"))
    def test_raises_poll_error_on_psutil_failure(self, _):
        with self.assertRaises(PollError):
            _collect_snapshot(2.0)


class SystemPollerTests(unittest.TestCase):
    def _make_snapshot(self):
        return SystemSnapshot(
            cpu_percent=(5.0,),
            mem_used=1024, mem_total=4096,
            swap_used=0, swap_total=0,
            load_avg=(0.1, 0.1, 0.1),
            top_procs=(),
        )

    def test_calls_on_snapshot_after_start(self):
        received = []
        snap = self._make_snapshot()

        with patch("etui_system.poller._collect_snapshot", return_value=snap):
            with patch("etui_system.poller.psutil.cpu_percent"):
                poller = SystemPoller(interval=0.05, on_snapshot=received.append)
                poller.start()
                time.sleep(0.2)
                poller.stop()

        self.assertGreater(len(received), 0)
        self.assertIsInstance(received[0], SystemSnapshot)

    def test_stop_terminates_thread_quickly(self):
        with patch("etui_system.poller._collect_snapshot", return_value=self._make_snapshot()):
            with patch("etui_system.poller.psutil.cpu_percent"):
                poller = SystemPoller(interval=0.05, on_snapshot=lambda _: None)
                poller.start()
                t0 = time.monotonic()
                poller.stop()
                elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 1.0)
        self.assertIsNone(poller._thread)

    def test_set_interval_updates_value(self):
        poller = SystemPoller(interval=2.0, on_snapshot=lambda _: None)
        poller.set_interval(5.0)
        self.assertEqual(poller.interval, 5.0)

    def test_set_interval_clamps_below_minimum(self):
        poller = SystemPoller(interval=2.0, on_snapshot=lambda _: None)
        poller.set_interval(0.0)
        self.assertGreaterEqual(poller.interval, 0.5)

    def test_start_is_idempotent(self):
        with patch("etui_system.poller._collect_snapshot", return_value=self._make_snapshot()):
            with patch("etui_system.poller.psutil.cpu_percent"):
                poller = SystemPoller(interval=0.05, on_snapshot=lambda _: None)
                poller.start()
                thread_1 = poller._thread
                poller.start()
                thread_2 = poller._thread
                poller.stop()
        self.assertIs(thread_1, thread_2)

    def test_poll_error_is_swallowed(self):
        """A PollError during a tick must not crash the poller thread."""
        call_count = [0]

        def boom(_interval):
            call_count[0] += 1
            raise PollError("boom")

        with patch("etui_system.poller._collect_snapshot", side_effect=boom):
            with patch("etui_system.poller.psutil.cpu_percent"):
                poller = SystemPoller(interval=0.05, on_snapshot=lambda _: None)
                poller.start()
                time.sleep(0.2)
                poller.stop()

        self.assertGreater(call_count[0], 0)
