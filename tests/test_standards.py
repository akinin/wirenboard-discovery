from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "wirenboard_discovery"
    / "standards.py"
)
SPEC = importlib.util.spec_from_file_location("wb_standards", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
standards = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(standards)


class IdentifierTest(unittest.TestCase):
    def test_canonical_identifier(self) -> None:
        self.assertTrue(standards.is_canonical_id("setpoint_t_room"))
        self.assertFalse(standards.is_canonical_id("Room Temperature"))
        self.assertFalse(standards.is_canonical_id("temperature_"))

    def test_sensor_prefixes(self) -> None:
        self.assertEqual(
            standards.canonical_sensor_device_class("t_mcu"), "temperature"
        )
        self.assertEqual(
            standards.canonical_sensor_device_class("e_ap_total"), "energy"
        )
        self.assertEqual(
            standards.canonical_sensor_device_class("humidity_outdoor"),
            "humidity",
        )
        self.assertEqual(standards.canonical_sensor_unit("temperature"), "deg C")
        self.assertEqual(standards.canonical_sensor_unit("illuminance"), "lx")
        self.assertEqual(standards.canonical_sensor_unit("v_vin"), "V")

    def test_alarm_classes(self) -> None:
        self.assertEqual(
            standards.canonical_binary_device_class("alarm_motion"), "motion"
        )
        self.assertEqual(
            standards.canonical_binary_device_class("alarm_tamper"), "tamper"
        )
        self.assertEqual(
            standards.canonical_binary_device_class("alarm_overheating"),
            "problem",
        )

    def test_service_channels_are_diagnostic(self) -> None:
        self.assertTrue(standards.is_diagnostic_id("sn"))
        self.assertTrue(standards.is_diagnostic_id("v_vin"))
        self.assertFalse(standards.is_diagnostic_id("temperature"))


if __name__ == "__main__":
    unittest.main()
