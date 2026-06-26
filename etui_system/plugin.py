# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmicio LLC

from textual.widget import Widget

from etui.plugin import EtuiTabPlugin, TabSpec

from .bus_contract import (
    SVC_SYSTEM_KILL,
    SVC_SYSTEM_METRICS,
    SVC_SYSTEM_PROCESS_INFO,
    SVC_SYSTEM_PROCESS_LIST,
    SVC_SYSTEM_RESUME,
    SVC_SYSTEM_SET_POLL_INTERVAL,
    SVC_SYSTEM_SUSPEND,
)


class SystemTabPlugin(EtuiTabPlugin):
    def spec(self) -> TabSpec:
        from .tab import SystemTab

        return TabSpec(
            id="plugin-system",
            title="System",
            order=450,
            provides=(
                SVC_SYSTEM_METRICS,
                SVC_SYSTEM_PROCESS_LIST,
                SVC_SYSTEM_PROCESS_INFO,
                SVC_SYSTEM_KILL,
                SVC_SYSTEM_SUSPEND,
                SVC_SYSTEM_RESUME,
                SVC_SYSTEM_SET_POLL_INTERVAL,
            ),
            settings_schema=SystemTab.settings_schema,
        )

    def create_widget(self) -> Widget:
        from .tab import SystemTab

        return SystemTab()
