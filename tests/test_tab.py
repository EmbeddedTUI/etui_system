# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmicio LLC

import signal
import unittest
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult

from etui_system.bus_contract import (
    ProcessKilled,
    ProcessNotFound,
    PermissionDenied,
    SystemSnapshot,
    TOPIC_SYSTEM_SNAPSHOT,
)
from etui_system.tab import SystemTab
from etui_system.widgets.cpu_bars import CpuBars
from etui_system.widgets.mem_gauge import MemGauge
from etui_system.widgets.process_table import ProcessTable


def _make_snapshot(n_cpu=2, n_procs=5):
    procs = tuple(
        {"pid": i + 1, "name": f"proc{i}", "user": "tester",
         "cpu": float(10 - i), "mem_pct": 1.0, "rss": 1024 * 1024,
         "vms": 2 * 1024 * 1024, "status": "running", "cmd": f"proc{i}"}
        for i in range(n_procs)
    )
    return SystemSnapshot(
        cpu_percent=tuple(float(i * 10) for i in range(n_cpu)),
        mem_used=2 * 1024 ** 3, mem_total=8 * 1024 ** 3,
        swap_used=0, swap_total=0,
        load_avg=(0.5, 0.4, 0.3),
        top_procs=procs,
    )


class SystemTestApp(App):
    def compose(self) -> ComposeResult:
        # Prevent poller from actually starting during tests.
        yield SystemTab()


class SystemTabSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_schema_has_required_fields(self):
        keys = {f.key for f in SystemTab.settings_schema.fields}
        for expected in ("poll_interval", "max_processes", "default_sort",
                         "tree_view", "show_threads", "cpu_bar_height", "highlight_user"):
            self.assertIn(expected, keys)

    async def test_apply_settings_updates_poll_interval(self):
        tab = SystemTab()
        tab.apply_settings({"poll_interval": 10})
        self.assertEqual(tab._poll_interval, 10.0)

    async def test_apply_settings_updates_max_processes(self):
        tab = SystemTab()
        tab.apply_settings({"max_processes": 200})
        self.assertEqual(tab._max_procs, 200)

    async def test_apply_settings_updates_sort_col(self):
        tab = SystemTab()
        tab.apply_settings({"default_sort": "mem"})
        self.assertEqual(tab._sort_col, "mem")

    async def test_env_var_overrides_poll_interval(self):
        tab = SystemTab()
        with patch.dict("os.environ", {"ETUI_SYSTEM_POLL": "7"}):
            tab.apply_settings({"poll_interval": 2})
        self.assertEqual(tab._poll_interval, 7.0)


class SystemTabMountTests(unittest.IsolatedAsyncioTestCase):
    async def test_tab_mounts_with_cpu_bars(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                self.assertIsNotNone(app.query_one(CpuBars))

    async def test_tab_mounts_with_mem_gauge(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                self.assertIsNotNone(app.query_one(MemGauge))

    async def test_tab_mounts_with_process_table(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                self.assertIsNotNone(app.query_one(ProcessTable))

    async def test_survives_leave_returns_true(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test() as pilot:
                tab = app.query_one(SystemTab)
                self.assertTrue(tab.survives_leave())


class SystemTabSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_on_snapshot_populates_process_table(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                tab = app.query_one(SystemTab)
                snap = _make_snapshot(n_cpu=4, n_procs=5)
                tab._on_snapshot(snap)
                await pilot.pause()
                tbl = app.query_one(ProcessTable)
                self.assertGreater(tbl.row_count, 0)

    async def test_on_snapshot_emits_bus_event(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                tab = app.query_one(SystemTab)
                received = []
                if tab.bus is not None:
                    tab.bus.subscribe(TOPIC_SYSTEM_SNAPSHOT, received.append)
                snap = _make_snapshot()
                tab._on_snapshot(snap)
                await pilot.pause()
                if tab.bus is not None:
                    self.assertEqual(len(received), 1)

    async def test_last_snapshot_stored(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                tab = app.query_one(SystemTab)
                snap = _make_snapshot()
                tab._on_snapshot(snap)
                await pilot.pause()
                self.assertIs(tab._last_snapshot, snap)


class SystemTabServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_svc_metrics_returns_empty_before_snapshot(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test() as pilot:
                tab = app.query_one(SystemTab)
                self.assertEqual(tab._svc_metrics(), {})

    async def test_svc_metrics_returns_dict_after_snapshot(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test() as pilot:
                tab = app.query_one(SystemTab)
                tab._last_snapshot = _make_snapshot()
                m = tab._svc_metrics()
                self.assertIn("cpu_percent", m)
                self.assertIn("mem_used", m)
                self.assertIn("load_avg", m)

    async def test_svc_process_list_returns_empty_before_snapshot(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test() as pilot:
                tab = app.query_one(SystemTab)
                self.assertEqual(tab._svc_process_list(), [])

    async def test_svc_process_list_respects_limit(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test() as pilot:
                tab = app.query_one(SystemTab)
                tab._last_snapshot = _make_snapshot(n_procs=10)
                result = tab._svc_process_list(limit=3)
                self.assertLessEqual(len(result), 3)

    async def test_svc_kill_raises_process_not_found(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test() as pilot:
                tab = app.query_one(SystemTab)
                import psutil as _psutil
                with patch.object(_psutil, "Process") as MockProc:
                    MockProc.return_value.send_signal.side_effect = _psutil.NoSuchProcess(99999)
                    with self.assertRaises(ProcessNotFound):
                        tab._svc_kill(99999, signal.SIGTERM)

    async def test_svc_kill_raises_permission_denied(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            MockPoller.return_value.start = MagicMock()
            async with app.run_test() as pilot:
                tab = app.query_one(SystemTab)
                import psutil as _psutil
                with patch.object(_psutil, "Process") as MockProc:
                    MockProc.return_value.send_signal.side_effect = _psutil.AccessDenied(1)
                    with self.assertRaises(PermissionDenied):
                        tab._svc_kill(1, signal.SIGKILL)

    async def test_svc_set_poll_interval_updates_poller(self):
        app = SystemTestApp()
        with patch("etui_system.tab.SystemPoller") as MockPoller:
            mock_instance = MagicMock()
            MockPoller.return_value = mock_instance
            async with app.run_test() as pilot:
                tab = app.query_one(SystemTab)
                tab._svc_set_poll_interval(5.0)
                mock_instance.set_interval.assert_called_with(5.0)
                self.assertEqual(tab._poll_interval, 5.0)
