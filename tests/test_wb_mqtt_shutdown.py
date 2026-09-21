"""Regression tests for Paho callbacks racing Home Assistant shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path
import importlib.util
import sys
import threading
import types
import unittest
from unittest.mock import patch


COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "wirenboard_discovery"
PACKAGE_NAME = "wb_shutdown_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(COMPONENT_PATH)]
sys.modules[PACKAGE_NAME] = package

for module_name in ("const", "models"):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{module_name}", COMPONENT_PATH / f"{module_name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

paho = types.ModuleType("paho")
paho_mqtt = types.ModuleType("paho.mqtt")
paho_client = types.ModuleType("paho.mqtt.client")
paho_mqtt.client = paho_client
paho.mqtt = paho_mqtt
sys.modules.setdefault("paho", paho)
sys.modules.setdefault("paho.mqtt", paho_mqtt)
sys.modules.setdefault("paho.mqtt.client", paho_client)

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.wb_mqtt", COMPONENT_PATH / "wb_mqtt.py"
)
assert spec is not None and spec.loader is not None
wb_mqtt = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wb_mqtt
spec.loader.exec_module(wb_mqtt)


class RecordingLoop:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.closed = False
        self.unexpected_error = False

    def call_soon_threadsafe(self, callback, *args) -> None:
        if self.unexpected_error:
            raise RuntimeError("unexpected scheduler failure")
        if self.closed:
            raise RuntimeError("Event loop is closed")
        self.calls.append((callback, args))

    def is_closed(self) -> bool:
        return self.closed


class FakeClient:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.calls: list[str] = []

    def disconnect(self) -> None:
        self.calls.append("disconnect")
        self.runtime._on_disconnect(self, None, None, None, None)

    def loop_stop(self) -> None:
        self.calls.append("loop_stop")


def make_runtime(loop) -> tuple[wb_mqtt.WBRuntimeClient, FakeClient]:
    runtime = wb_mqtt.WBRuntimeClient.__new__(wb_mqtt.WBRuntimeClient)
    runtime._loop = loop
    runtime._prefix = "/"
    runtime._parser = wb_mqtt.WBTopicParser("/")
    runtime._callbacks = {}
    runtime._meta_callbacks = {}
    runtime._device_meta_callbacks = {}
    runtime._connection_callbacks = []
    runtime._inventory_callbacks = []
    runtime._connected = threading.Event()
    runtime._stopping = threading.Event()
    runtime._stop_lock = asyncio.Lock() if not isinstance(loop, RecordingLoop) else None
    runtime._stopped = False
    client = FakeClient(runtime)
    runtime._client = client
    return runtime, client


class ShutdownTest(unittest.TestCase):
    def test_clean_stop_drops_late_message_and_disconnect_callback(self) -> None:
        loop = RecordingLoop()
        runtime, client = make_runtime(loop)
        values = []
        connections = []
        runtime.subscribe_value("test/temperature", values.append)
        runtime._connection_callbacks.append(connections.append)
        runtime._connected.set()

        with patch.object(wb_mqtt._LOGGER, "warning") as warning:
            runtime._stop()
        warning.assert_not_called()
        runtime._on_message(
            client,
            None,
            types.SimpleNamespace(
                topic="/devices/test/controls/temperature",
                payload=b"21",
                retain=False,
            ),
        )

        self.assertEqual(client.calls, ["disconnect", "loop_stop"])
        self.assertFalse(runtime.connected)
        self.assertEqual(loop.calls, [])
        self.assertEqual(values, [])
        self.assertEqual(connections, [])

    def test_closed_loop_drops_message_without_paho_thread_exception(self) -> None:
        loop = RecordingLoop()
        loop.closed = True
        runtime, client = make_runtime(loop)
        runtime.subscribe_value("test/temperature", lambda value: None)
        message = types.SimpleNamespace(
            topic="/devices/test/controls/temperature",
            payload=b"21",
            retain=False,
        )

        runtime._on_message(client, None, message)
        self.assertTrue(runtime._stopping.is_set())
        self.assertEqual(loop.calls, [])
        runtime._on_message(client, None, message)

    def test_unexpected_loop_error_is_not_hidden(self) -> None:
        loop = RecordingLoop()
        loop.unexpected_error = True
        runtime, _client = make_runtime(loop)
        with self.assertRaisesRegex(RuntimeError, "unexpected scheduler failure"):
            runtime._schedule_callback(lambda: None)
        self.assertFalse(runtime._stopping.is_set())

    def test_unexpected_disconnect_remains_visible(self) -> None:
        loop = RecordingLoop()
        runtime, client = make_runtime(loop)
        runtime._connected.set()
        callback = lambda connected: None
        runtime._connection_callbacks.append(callback)

        with self.assertLogs(wb_mqtt._LOGGER, level="WARNING") as logs:
            runtime._on_disconnect(client, None, None, None, None)

        self.assertIn("connection was lost", logs.output[0])
        self.assertEqual(loop.calls, [(callback, (False,))])

    def test_concurrent_stop_is_idempotent(self) -> None:
        async def stop_twice() -> list[str]:
            runtime, client = make_runtime(asyncio.get_running_loop())
            await asyncio.gather(runtime.async_stop(), runtime.async_stop())
            return client.calls

        self.assertEqual(asyncio.run(stop_twice()), ["disconnect", "loop_stop"])

    def test_stop_before_start_does_not_restart_worker(self) -> None:
        async def stop_then_start() -> list[str]:
            runtime, client = make_runtime(asyncio.get_running_loop())
            await runtime.async_stop()
            with self.assertRaisesRegex(wb_mqtt.WBDiscoveryError, "stopping"):
                await runtime.async_start()
            return client.calls

        self.assertEqual(asyncio.run(stop_then_start()), ["disconnect", "loop_stop"])


if __name__ == "__main__":
    unittest.main()
