from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "wirenboard_discovery"
    / "units.py"
)
SPEC = importlib.util.spec_from_file_location("wb_units", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
units = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(units)


class DisplayUnitTest(unittest.TestCase):
    def test_temperature_aliases(self) -> None:
        self.assertEqual(units.display_unit("deg C"), "°C")
        self.assertEqual(units.display_unit("℃"), "°C")
        self.assertEqual(units.display_unit("deg F"), "°F")

    def test_humidity_aliases(self) -> None:
        self.assertEqual(units.display_unit("%, RH"), "%")
        self.assertEqual(units.display_unit("% RH"), "%")

    def test_volume_aliases(self) -> None:
        self.assertEqual(units.display_unit("m^3"), "m³")
        self.assertEqual(units.display_unit("м3"), "m³")

    def test_explicit_sound_units_are_preserved(self) -> None:
        self.assertEqual(units.display_unit("dB"), "dB")
        self.assertEqual(units.display_unit("dBA"), "dBA")

    def test_unknown_and_empty_units(self) -> None:
        self.assertEqual(units.display_unit(" kWh "), "kWh")
        self.assertIsNone(units.display_unit(None))


if __name__ == "__main__":
    unittest.main()
