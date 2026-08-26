from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "wirenboard_discovery"
    / "climate_modes.py"
)
SPEC = importlib.util.spec_from_file_location("wb_climate_modes", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
climate_modes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(climate_modes)


R8C_MODES = {
    "0": "Cooling",
    "1": "Ventilation",
    "2": "Heating",
    "3": "Floor heating",
    "4": "Heating+Floor heating",
}


class ClimateModesTest(unittest.TestCase):
    def test_r8c_heating_is_not_mapped_to_ventilation(self) -> None:
        self.assertEqual(
            climate_modes.resolve_hvac_mode("2", R8C_MODES, default="heat"),
            "heat",
        )

    def test_r8c_enum_modes_are_mapped_by_label(self) -> None:
        self.assertEqual(
            climate_modes.resolve_hvac_mode("0", R8C_MODES, default="heat"),
            "cool",
        )
        self.assertEqual(
            climate_modes.resolve_hvac_mode("1", R8C_MODES, default="heat"),
            "fan_only",
        )
        self.assertEqual(
            climate_modes.resolve_hvac_mode("3", R8C_MODES, default="heat"),
            "heat",
        )

    def test_r8c_available_modes_include_enum_capabilities(self) -> None:
        self.assertEqual(
            climate_modes.available_hvac_modes("thermostat", R8C_MODES),
            ["off", "heat", "cool", "fan_only"],
        )

    def test_r8c_mode_command_uses_enum_key(self) -> None:
        self.assertEqual(
            climate_modes.enum_key_for_hvac_mode("heat", R8C_MODES), "2"
        )

    def test_exact_mode_control_is_preferred(self) -> None:
        self.assertTrue(climate_modes.is_primary_mode_control("Mode", None))
        self.assertTrue(climate_modes.is_primary_mode_control("status", "Режим"))
        self.assertFalse(
            climate_modes.is_primary_mode_control(
                "Mode switch (floor heating only)", None
            )
        )


if __name__ == "__main__":
    unittest.main()
