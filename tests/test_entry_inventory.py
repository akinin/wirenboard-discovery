"""Regression tests for startup with an incomplete MQTT inventory."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock


@dataclass
class Control:
    control_type: str | None
    value: str | None = None


def load_inventory_functions():
    component = Path(__file__).parents[1] / "custom_components" / "wirenboard_discovery"
    namespace = {
        "CONF_HOST": "host",
        "CONF_PORT": "port",
        "CONF_USERNAME": "username",
        "CONF_PASSWORD": "password",
        "WBDiscoveryError": RuntimeError,
        "_entry_controls": lambda entry: entry.stored,
        "_LOGGER": Mock(),
        "callback": lambda fn: fn,
        "control_metadata_signature": lambda control: control.control_type,
        "discover_controls": Mock(),
        "replace": replace,
    }
    exec((component / "const.py").read_text(), namespace)
    tree = ast.parse((component / "__init__.py").read_text())
    names = {"_async_entry_controls", "_watch_selected_inventory", "_selected_inventory_signature"}
    functions = [node for node in tree.body if getattr(node, "name", None) in names]
    module = ast.Module(body=[tree.body[0], *functions], type_ignores=[])
    exec(compile(module, "wirenboard_discovery/__init__.py", "exec"), namespace)
    return namespace


class EntryInventoryTests(IsolatedAsyncioTestCase):
    async def test_partial_scan_keeps_missing_channels_and_the_type_of_value_only_channels(self):
        functions = load_inventory_functions()
        saved = {
            "wb-adc/Vin": Control("value", "12"),
            "wb-relay/K1": Control("switch", "0"),
            "wb-msw/Temperature": Control("temperature", "21"),
        }
        discovered = {
            "wb-adc/Vin": Control("value", "13"),
            "wb-relay/K1": Control(None, "1"),
            "wb-relay/K2": Control("switch", "1"),
        }
        entry = SimpleNamespace(data={"selected_controls": list(saved)}, options={}, stored=saved)
        hass = SimpleNamespace(async_add_executor_job=AsyncMock(return_value=discovered))
        controls = await functions["_async_entry_controls"](
            hass, entry, {"host": "wb.local", "port": 1884, "prefix": "/"}
        )

        self.assertEqual(
            controls,
            {
                "wb-adc/Vin": Control("value", "13"),
                "wb-relay/K1": Control("switch", "1"),
                "wb-msw/Temperature": Control("temperature", "21"),
            },
        )

    async def test_retained_return_of_unloaded_channel_is_handled_during_grace_period(self):
        functions = load_inventory_functions()
        timers = []
        reload_entry = AsyncMock()

        def call_later(_hass, delay, callback):
            timers.append((delay, callback))
            return Mock()

        functions["async_call_later"] = call_later
        existing = "wb-adc/Vin"
        missing = "wb-msw/Temperature"
        entry = SimpleNamespace(
            entry_id="entry",
            data={"selected_controls": [existing, missing]},
            options={},
            async_on_unload=Mock(),
        )
        live_controls = {existing: Control("value", "12")}
        client = SimpleNamespace(
            controls=live_controls,
            control_reported=lambda key: key in live_controls,
            subscribe_inventory=Mock(),
        )
        runtime = {"client": client, "controls": live_controls.copy()}
        hass = SimpleNamespace(
            data={functions["DOMAIN"]: {entry.entry_id: runtime}},
            config_entries=SimpleNamespace(async_reload=reload_entry),
        )

        functions["_watch_selected_inventory"](hass, entry, runtime)
        inventory_changed = client.subscribe_inventory.call_args.args[0]
        inventory_changed(True)
        self.assertEqual([delay for delay, _ in timers], [120.0])

        live_controls[missing] = Control("temperature", "21")
        inventory_changed(True)
        inventory_changed(True)
        self.assertEqual([delay for delay, _ in timers], [120.0, 2.0])
        await timers[-1][1](None)
        reload_entry.assert_awaited_once_with(entry.entry_id)
