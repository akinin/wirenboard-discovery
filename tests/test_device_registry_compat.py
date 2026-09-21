"""Test device registry compatibility with supported Home Assistant versions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


COMPONENT_PATH = Path(__file__).parents[1] / "custom_components" / "wirenboard_discovery"
PACKAGE_NAME = "wb_registry_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(COMPONENT_PATH)]
sys.modules[PACKAGE_NAME] = package

const_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.const", COMPONENT_PATH / "const.py"
)
assert const_spec is not None and const_spec.loader is not None
const = importlib.util.module_from_spec(const_spec)
sys.modules[const_spec.name] = const
const_spec.loader.exec_module(const)

homeassistant = types.ModuleType("homeassistant")
helpers = types.ModuleType("homeassistant.helpers")
device_registry = types.ModuleType("homeassistant.helpers.device_registry")
helpers.device_registry = device_registry
homeassistant.helpers = helpers
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault("homeassistant.helpers.device_registry", device_registry)

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.device_registry_compat",
    COMPONENT_PATH / "device_registry_compat.py",
)
assert spec is not None and spec.loader is not None
compat = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = compat
spec.loader.exec_module(compat)


class ModernDevice:
    config_entry_id = "owner"

    @property
    def config_entries(self):
        raise AssertionError("Deprecated config_entries must not be read")


class LegacyDevice:
    config_entries = {"owner"}


class CompositeDevice:
    is_composite_device = True
    config_entry_id = "primary"
    config_entries = {"primary", "owner"}


class RegistryCompatTest(unittest.TestCase):
    def test_modern_lookup_is_scoped_to_config_entry(self) -> None:
        class Registry:
            def async_get_device_by_identifier(self, identifier, entry_id):
                self.args = identifier, entry_id
                return ModernDevice()

        registry = Registry()
        device = compat.get_device_by_identifier(registry, "wb-1", "owner")
        self.assertEqual(registry.args, ((const.DOMAIN, "wb-1"), "owner"))
        self.assertTrue(compat.device_belongs_to_entry(device, "owner"))
        self.assertFalse(compat.device_belongs_to_entry(device, "other"))

    def test_legacy_lookup_remains_compatible(self) -> None:
        class Registry:
            def async_get_device(self, *, identifiers):
                self.identifiers = identifiers
                return LegacyDevice()

        registry = Registry()
        device = compat.get_device_by_identifier(registry, "wb-1", "owner")
        self.assertEqual(registry.identifiers, {(const.DOMAIN, "wb-1")})
        self.assertTrue(compat.device_belongs_to_entry(device, "owner"))
        self.assertFalse(compat.device_belongs_to_entry(device, "other"))

    def test_restored_composite_uses_all_split_entry_ids(self) -> None:
        device = CompositeDevice()
        self.assertTrue(compat.device_belongs_to_entry(device, "primary"))
        self.assertTrue(compat.device_belongs_to_entry(device, "owner"))
        self.assertFalse(compat.device_belongs_to_entry(device, "other"))


if __name__ == "__main__":
    unittest.main()
