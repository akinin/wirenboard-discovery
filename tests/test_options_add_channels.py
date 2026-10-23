"""Exercise the production options flow with Home Assistant UI boundaries stubbed."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock


COMPONENT = Path(__file__).parents[1] / "custom_components/wirenboard_discovery"
spec = importlib.util.spec_from_file_location("wb_options_models", COMPONENT / "models.py")
models = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = models
spec.loader.exec_module(models)


class Required:
    def __init__(self, key, default=None):
        self.key, self.default = key, default


class OptionsBoundary:
    def async_show_menu(self, **kwargs):
        return {"type": "menu", **kwargs}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


def load_flow():
    namespace = {
        "CONF_HOST": "host", "CONF_PORT": "port",
        "CONF_USERNAME": "username", "CONF_PASSWORD": "password",
        "OptionsBoundary": OptionsBoundary,
        "vol": SimpleNamespace(Schema=dict, Required=Required),
        "selector": SimpleNamespace(
            SelectSelectorConfig=lambda **kwargs: kwargs,
            SelectSelector=lambda config: config,
            SelectOptionDict=dict,
        ),
        "default_group_type": lambda group_id, group: group.get("type", "device"),
    }
    exec((COMPONENT / "const.py").read_text(), namespace)
    tree = ast.parse((COMPONENT / "config_flow.py").read_text())
    helpers = {
        "_visible_controls", "_is_system_device", "_select_options",
        "_control_membership", "_control_label", "control_to_dict",
    }
    methods = {
        "__init__", "async_step_init", "async_step_controls", "_options_with",
        "_current_selected_controls", "_current_removed_controls", "_current_groups",
        "_current_inverted_binary_sensors", "_show_system_devices",
        "_current_connection", "_connection_options",
    }
    body = [tree.body[0]]  # Keep postponed annotations, like the production module.
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in {"SYSTEM_DEVICE_IDS", "SYSTEM_DEVICE_PREFIXES"}
            for target in node.targets
        ):
            body.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in helpers:
            body.append(node)
        if isinstance(node, ast.ClassDef) and node.name == "WirenBoardOptionsFlow":
            node.bases = [ast.Name(id="OptionsBoundary", ctx=ast.Load())]
            node.body = [member for member in node.body if getattr(member, "name", None) in methods]
            body.append(node)
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), "config_flow.py", "exec"), namespace)
    return namespace


def field(form, key):
    return next((marker, config) for marker, config in form["data_schema"].items() if marker.key == key)


class AddChannelsTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.code = load_flow()
        self.old = models.WBControl("wb-mr6c_1", "K1", control_type="switch", readonly=False)
        self.new = models.WBControl("wb-mr6c_1", "K2", control_type="switch", readonly=False)
        self.sensor = models.WBControl("wb-msw_2", "Temperature", control_type="temperature", readonly=True)
        self.system = models.WBControl("system", "Uptime", readonly=True)
        self.hidden = models.WBControl("wb-mr6c_1", "Secret", meta={"hidden": True})
        self.entry = SimpleNamespace(
            data={"host": "wb.local", "port": 1883, "prefix": "/", "selected_controls": [self.old.key]},
            options={},
        )
        self.flow = self.code["WirenBoardOptionsFlow"](self.entry)
        self.flow._controls = {c.key: c for c in [self.old, self.new, self.sensor, self.system, self.hidden]}
        self.flow._async_load_controls = AsyncMock(return_value={})

    async def submit(self, keys=(), show_system=False):
        return await self.flow.async_step_controls({
            "selected_controls": list(keys), "show_system_devices": show_system,
        })

    async def test_options_menu_exposes_add_channels(self):
        result = await self.flow.async_step_init()
        self.assertIn("controls", result["menu_options"])

    async def test_form_only_lists_additional_visible_channels(self):
        result = await self.flow.async_step_controls()
        marker, config = field(result, "selected_controls")
        self.assertEqual(marker.default, [])
        self.assertEqual({option["value"] for option in config["options"]}, {self.new.key, self.sensor.key})

    async def test_add_channels_preserves_selection_without_creating_groups(self):
        result = await self.submit([self.new.key, self.sensor.key])
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(set(result["data"]["selected_controls"]), {self.old.key, self.new.key, self.sensor.key})
        self.assertEqual(result["data"]["device_groups"], {})
        self.assertEqual(set(result["data"]["discovered_controls"]), {self.old.key, self.new.key, self.sensor.key})
        self.assertIsNone(result["data"]["discovered_controls"][self.new.key]["ha_device_id"])

    async def test_empty_submission_does_not_remove_existing_channels(self):
        result = await self.submit()
        self.assertEqual(result["data"]["selected_controls"], [self.old.key])

    async def test_previous_selection_in_payload_is_harmless(self):
        result = await self.submit([self.old.key, self.new.key])
        self.assertEqual(result["data"]["selected_controls"], sorted([self.old.key, self.new.key]))

    async def test_readding_removed_channel_clears_only_its_removal_marker(self):
        self.entry.options["removed_controls"] = [self.new.key, "other/removed"]
        result = await self.submit([self.new.key])
        self.assertEqual(result["data"]["removed_controls"], ["other/removed"])

    async def test_unavailable_selected_channel_keeps_stored_metadata(self):
        stored = self.code["control_to_dict"](self.old)
        self.entry.data["discovered_controls"] = {self.old.key: stored}
        del self.flow._controls[self.old.key]
        result = await self.submit([self.new.key])
        self.assertIn(self.old.key, result["data"]["selected_controls"])
        self.assertEqual(result["data"]["discovered_controls"][self.old.key], stored)

    async def test_existing_groups_and_inversion_are_preserved(self):
        group = {"name": "Existing", "type": "device", "controls": [self.old.key], "icon": "", "roles": {}, "expose_controls": []}
        self.entry.options.update(device_groups={"existing": group}, inverted_binary_sensors=["input/1"])
        result = await self.submit([self.new.key])
        self.assertEqual(result["data"]["device_groups"], {"existing": group})
        self.assertEqual(result["data"]["inverted_binary_sensors"], ["input/1"])

    async def test_system_filter_refreshes_choices_before_saving(self):
        refreshed = await self.submit([self.new.key], show_system=True)
        self.assertEqual(refreshed["type"], "form")
        marker, config = field(refreshed, "selected_controls")
        self.assertEqual(marker.default, [self.new.key])
        self.assertIn(self.system.key, {option["value"] for option in config["options"]})
        result = await self.submit([self.new.key, self.system.key], show_system=True)
        self.assertTrue(result["data"]["show_system_devices"])
        self.assertIn(self.old.key, result["data"]["selected_controls"])

    async def test_discovery_error_never_saves_options(self):
        self.flow._async_load_controls.return_value = {"base": "cannot_connect"}
        result = await self.submit([self.new.key])
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "cannot_connect"})

    async def test_hidden_and_unknown_channels_cannot_be_added(self):
        for key in (self.hidden.key, "unknown/channel", self.system.key):
            with self.subTest(key=key):
                result = await self.submit([key])
                self.assertEqual(result["type"], "form")
                self.assertEqual(result["errors"], {"selected_controls": "invalid_controls"})

    async def test_different_supported_channel_types_can_be_added(self):
        controls = [
            models.WBControl("module", str(i), control_type=kind, readonly=readonly)
            for i, (kind, readonly) in enumerate([
                ("temperature", True), ("value", True), ("switch", True),
                ("pushbutton", False), ("text", False), ("range", False),
            ])
        ]
        self.flow._controls.update({control.key: control for control in controls})
        result = await self.submit([control.key for control in controls])
        self.assertEqual(len(result["data"]["selected_controls"]), len(controls) + 1)

    async def test_new_channels_reuse_the_existing_physical_device_identity(self):
        tree = ast.parse((COMPONENT / "entity.py").read_text())
        entity_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "WBEntity")
        update = next(node for node in entity_class.body if getattr(node, "name", None) == "_update_device_info")
        helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        namespace = {"DeviceInfo": dict, "DOMAIN": "wirenboard_discovery", "identity_metadata_key": lambda key: None, "localized_title": models.localized_title}
        exec(compile(ast.Module(body=[tree.body[0], *helpers, update], type_ignores=[]), "entity.py", "exec"), namespace)
        result = await self.submit([self.new.key])
        identities = []
        for key in [self.old.key, self.new.key]:
            control = models.WBControl(**result["data"]["discovered_controls"][key])
            entity = SimpleNamespace(_control=control, _device_meta={}, _client=SimpleNamespace(language="ru"))
            namespace["_update_device_info"](entity)
            identities.append(entity._attr_device_info["identifiers"])
        self.assertEqual(identities[0], {("wirenboard_discovery", self.old.device_id)})
        self.assertEqual(identities[0], identities[1])
