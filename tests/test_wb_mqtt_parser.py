from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


COMPONENT_PATH = (
    Path(__file__).parents[1] / "custom_components" / "wirenboard_discovery"
)
PACKAGE_NAME = "wb_parser_test_package"

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

SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.wb_mqtt", COMPONENT_PATH / "wb_mqtt.py"
)
assert SPEC is not None and SPEC.loader is not None
wb_mqtt = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wb_mqtt
SPEC.loader.exec_module(wb_mqtt)


class TopicParserTest(unittest.TestCase):
    def test_device_meta_and_error_subtopic(self) -> None:
        parser = wb_mqtt.WBTopicParser("/")
        parser.parse_message(
            "/devices/test_device/meta",
            '{"title":{"en":"Test"},"error":"r"}',
        )
        self.assertEqual(parser.devices["test_device"], "Test")
        self.assertEqual(parser.device_meta["test_device"]["error"], "r")

        parser.parse_message("/devices/test_device/meta/error", "")
        self.assertEqual(parser.device_meta["test_device"]["error"], "")

    def test_control_hidden_and_error_metadata(self) -> None:
        parser = wb_mqtt.WBTopicParser("/")
        parser.parse_message(
            "/devices/test_device/controls/secret/meta",
            '{"type":"value","readonly":true,"hidden":true}',
        )
        parser.parse_message(
            "/devices/test_device/controls/secret/meta/error", "rp"
        )
        control = parser.controls["test_device/secret"]
        self.assertTrue(control.is_hidden)
        self.assertEqual(control.meta["error"], "rp")

    def test_device_metadata_is_copied_to_controls(self) -> None:
        parser = wb_mqtt.WBTopicParser("/")
        parser.parse_message(
            "/devices/wb-test/meta",
            '{"driver":"wb-modbus","title":{"en":"Test module"}}',
        )
        parser.parse_message("/devices/wb-test/controls/temperature", "21.5")
        control = parser.controls["wb-test/temperature"]
        self.assertEqual(control.device_meta["driver"], "wb-modbus")

    def test_legacy_system_identity_controls_enrich_device_metadata(self) -> None:
        parser = wb_mqtt.WBTopicParser("/")
        parser.parse_message("/devices/system/controls/Short SN", "AAEYWSY6")
        parser.parse_message("/devices/system/controls/HW Revision", "8.5.3")
        parser.parse_message("/devices/system/controls/Release name", "unstable.latest")
        control = parser.controls["system/Short SN"]
        self.assertEqual(control.device_meta["serial_number"], "AAEYWSY6")
        self.assertEqual(control.device_meta["hw_version"], "8.5.3")
        self.assertEqual(control.device_meta["sw_version"], "unstable.latest")

    def test_inventory_signature_ignores_live_error_metadata(self) -> None:
        control = wb_mqtt.WBControl(
            device_id="wb-test",
            control_id="temperature",
            control_name="Temperature",
            control_type="temperature",
            readonly=True,
            units="deg C",
            meta={"type": "temperature", "error": ""},
            device_meta={"driver": "wb-modbus", "error": ""},
        )
        before = wb_mqtt.control_metadata_signature(control)

        control.meta["error"] = "r"
        control.device_meta["error"] = "device disconnected"
        self.assertEqual(before, wb_mqtt.control_metadata_signature(control))

        control.meta["hidden"] = True
        self.assertNotEqual(before, wb_mqtt.control_metadata_signature(control))


if __name__ == "__main__":
    unittest.main()
