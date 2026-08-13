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

SMS_MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "wirenboard_discovery"
    / "sms.py"
)
SMS_SPEC = importlib.util.spec_from_file_location("wb_sms", SMS_MODULE_PATH)
assert SMS_SPEC is not None and SMS_SPEC.loader is not None
sms = importlib.util.module_from_spec(SMS_SPEC)
import sys
sys.modules[SMS_SPEC.name] = sms
SMS_SPEC.loader.exec_module(sms)


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


class SmsAttemptTrackerTest(unittest.TestCase):
    def test_collects_and_classifies_attempt(self) -> None:
        tracker = sms.SmsAttemptTracker()
        tracker.update("last_sent_time", "2026-08-13T10:00:00Z")
        tracker.update("last_message_text", "Проверка")
        tracker.update("last_recipient_number", "+79991234567")
        tracker.update("last_result", "Команда отправки передана")

        attempt = tracker.pending_attempt()
        self.assertIsNotNone(attempt)
        self.assertFalse(attempt.failed)
        self.assertTrue(tracker.script_controls_available)

        tracker.mark_emitted(attempt)
        self.assertIsNone(tracker.pending_attempt())

    def test_error_result_is_failed(self) -> None:
        tracker = sms.SmsAttemptTracker()
        for field, value in {
            "last_sent_time": "2026-08-13T10:01:00Z",
            "last_message_text": "Проверка",
            "last_recipient_number": "+79991234567",
            "last_result": "Ошибка: модем недоступен",
        }.items():
            tracker.update(field, value)
        self.assertTrue(tracker.pending_attempt().failed)


if __name__ == "__main__":
    unittest.main()
