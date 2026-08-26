from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "wirenboard_discovery"
    / "models.py"
)
SPEC = importlib.util.spec_from_file_location("wb_models", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
models = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = models
SPEC.loader.exec_module(models)


class ControlMetadataTest(unittest.TestCase):
    def test_hidden_metadata(self) -> None:
        self.assertTrue(
            models.WBControl("device", "secret", meta={"hidden": True}).is_hidden
        )
        self.assertFalse(
            models.WBControl("device", "visible", meta={"hidden": "0"}).is_hidden
        )

    def test_error_flags(self) -> None:
        for value in ("r", "w", "p", "rw"):
            with self.subTest(value=value):
                self.assertTrue(models.has_meta_error(value))
        for value in (None, "", "0", "false", "null"):
            with self.subTest(value=value):
                self.assertFalse(models.has_meta_error(value))


if __name__ == "__main__":
    unittest.main()
