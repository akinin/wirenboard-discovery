from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .composite import TYPE_AC, TYPE_COVER, TYPE_COVER_GATE, TYPE_DEVICE, TYPE_THERMOSTAT, default_group_type
from .const import (
    CONF_DEVICE_GROUPS,
    CONF_PREFIX,
    CONF_SELECTED_CONTROLS,
    CONF_SHOW_SYSTEM_DEVICES,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_PREFIX,
    DEFAULT_SHOW_SYSTEM_DEVICES,
    DOMAIN,
)
from .models import WBControl
from .wb_mqtt import WBDiscoveryError, discover_controls, discover_snapshot

_LOGGER = logging.getLogger(__name__)


def _connection_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    user_input = user_input or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")): str,
            vol.Optional(CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_PREFIX, default=user_input.get(CONF_PREFIX, DEFAULT_PREFIX)): str,
            vol.Required(
                CONF_SHOW_SYSTEM_DEVICES,
                default=user_input.get(CONF_SHOW_SYSTEM_DEVICES, DEFAULT_SHOW_SYSTEM_DEVICES),
            ): bool,
        }
    )


def _mqtt_connection_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    user_input = user_input or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")): str,
            vol.Optional(CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_PREFIX, default=user_input.get(CONF_PREFIX, DEFAULT_PREFIX)): str,
        }
    )


def _control_schema(controls: dict[str, WBControl]) -> vol.Schema:
    options = _select_options(controls)
    return vol.Schema(
        {
            vol.Required(CONF_SELECTED_CONTROLS, default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, multiple=True)
            ),
        }
    )


def _select_options(
    controls: dict[str, WBControl],
    groups: dict[str, dict[str, Any]] | None = None,
    current_group_id: str | None = None,
) -> list[selector.SelectOptionDict]:
    membership = _control_membership(groups or {}, current_group_id)
    return [
        selector.SelectOptionDict(value=key, label=_control_label(key, control, membership))
        for key, control in sorted(controls.items())
    ]


class WirenBoardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._connection_data: dict[str, Any] = {}
        self._controls: dict[str, WBControl] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            self._connection_data = user_input
            try:
                self._controls = await self.hass.async_add_executor_job(
                    discover_controls,
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input.get(CONF_USERNAME) or None,
                    user_input.get(CONF_PASSWORD) or None,
                    user_input[CONF_PREFIX],
                )
            except WBDiscoveryError:
                _LOGGER.exception("Cannot discover Wiren Board devices")
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_pick_controls()

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input),
            errors=errors,
        )

    async def async_step_pick_controls(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            data = {
                **self._connection_data,
                CONF_SELECTED_CONTROLS: user_input[CONF_SELECTED_CONTROLS],
                "discovered_controls": {
                    key: control_to_dict(control)
                    for key, control in self._controls.items()
                    if key in user_input[CONF_SELECTED_CONTROLS]
                },
            }
            return self.async_create_entry(
                title=f"Wiren Board {self._connection_data[CONF_HOST]}",
                data=data,
            )

        if not self._controls:
            return self.async_show_form(
                step_id="pick_controls",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices_found"},
            )

        return self.async_show_form(
            step_id="pick_controls",
            data_schema=_control_schema(
                _visible_controls(
                    self._controls,
                    self._connection_data.get(CONF_SHOW_SYSTEM_DEVICES, DEFAULT_SHOW_SYSTEM_DEVICES),
                )
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WirenBoardOptionsFlow(config_entry)


class WirenBoardOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry
        self._controls: dict[str, WBControl] = {}
        self._edit_group_id: str | None = None
        self._pending_group_id: str | None = None
        self._pending_group: dict[str, Any] | None = None
        self._pending_old_group_id: str | None = None
        self._pending_object_key: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "controls",
                "add_group",
                "edit_group",
                "remove_group",
                "export_config",
                "import_config",
                "diagnostics",
                "connection",
            ],
        )

    async def async_step_connection(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._controls = await self.hass.async_add_executor_job(
                    discover_controls,
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input.get(CONF_USERNAME) or None,
                    user_input.get(CONF_PASSWORD) or None,
                    user_input[CONF_PREFIX],
                )
            except WBDiscoveryError:
                _LOGGER.exception("Cannot connect to updated Wiren Board MQTT settings")
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="",
                    data=self._options_with(connection=user_input),
                )

        return self.async_show_form(
            step_id="connection",
            data_schema=_mqtt_connection_schema(user_input or self._current_connection()),
            errors=errors,
        )

    async def async_step_controls(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())

        if user_input is not None:
            show_system = user_input[CONF_SHOW_SYSTEM_DEVICES]
            visible_keys = set(_visible_controls(self._controls, show_system))
            selected = set(user_input[CONF_SELECTED_CONTROLS])
            if not show_system:
                selected.update(set(self._current_selected_controls()) - visible_keys)
            return self.async_create_entry(
                title="",
                data=self._options_with(
                    selected_controls=sorted(selected),
                    show_system_devices=show_system,
                ),
            )

        show_system = self._show_system_devices()
        visible_controls = _visible_controls(self._controls, show_system)
        visible_keys = set(visible_controls)
        selected = [key for key in self._current_selected_controls() if key in visible_keys]
        options = _select_options(visible_controls)
        schema = vol.Schema(
            {
                vol.Required(CONF_SHOW_SYSTEM_DEVICES, default=show_system): bool,
                vol.Required(CONF_SELECTED_CONTROLS, default=selected): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="controls", data_schema=schema, errors=errors)

    async def async_step_add_group(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())
        groups = self._current_groups()

        if user_input is not None:
            group_id = _slug(user_input["group_id"] or user_input["group_name"])
            if not group_id:
                errors["group_id"] = "required"
            elif not user_input["group_controls"]:
                errors["group_controls"] = "required"
            else:
                groups[group_id] = {
                    "name": user_input["group_name"] or group_id,
                    "controls": user_input["group_controls"],
                    "type": user_input["group_type"],
                    "icon": user_input.get("group_icon") or "",
                    "roles": {},
                    "expose_controls": [],
                    "objects": {},
                }
                self._pending_group_id = group_id
                self._pending_group = groups[group_id]
                self._pending_old_group_id = None
                if user_input["group_type"] != TYPE_DEVICE:
                    return await self.async_step_add_group_roles()
                return await self.async_step_add_group_objects()

        schema = vol.Schema(
            {
                vol.Optional("group_id", default=""): str,
                vol.Required("group_name", default=""): str,
                vol.Required("group_type", default=TYPE_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_group_type_options())
                ),
                vol.Optional("group_icon", default=""): str,
                vol.Required("group_controls", default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_select_options(self._controls, groups),
                        multiple=True,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="add_group", data_schema=schema, errors=errors)

    async def async_step_add_group_roles(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())
        if not self._pending_group_id or not self._pending_group:
            return await self.async_step_add_group()

        if user_input is not None:
            group = dict(self._pending_group)
            group["roles"] = _roles_from_input(user_input)
            group["expose_controls"] = user_input.get("expose_controls", [])
            self._pending_group = group
            return await self.async_step_add_group_objects()

        schema = _role_schema(self._controls, self._pending_group)
        return self.async_show_form(step_id="add_group_roles", data_schema=schema, errors=errors)

    async def async_step_edit_group(self, user_input: dict[str, Any] | None = None):
        groups = self._current_groups()
        if not groups:
            return self.async_show_form(
                step_id="edit_group",
                data_schema=vol.Schema({}),
                errors={"base": "no_groups"},
            )

        if user_input is not None:
            self._edit_group_id = user_input["group_id"]
            return await self.async_step_edit_group_details()

        return self.async_show_form(
            step_id="edit_group",
            data_schema=vol.Schema(
                {
                    vol.Required("group_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=_group_options(groups))
                    ),
                }
            ),
        )

    async def async_step_edit_group_details(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())
        groups = self._current_groups()
        group_id = self._edit_group_id
        if not group_id or group_id not in groups:
            return await self.async_step_edit_group()

        group = groups[group_id]
        if user_input is not None:
            if not user_input["group_controls"]:
                errors["group_controls"] = "required"
            else:
                new_group_id = _slug(user_input["group_id"] or group_id)
                if not new_group_id:
                    errors["group_id"] = "required"
                elif new_group_id != group_id and new_group_id in groups:
                    errors["group_id"] = "already_exists"
                else:
                    groups.pop(group_id, None)
                    group_data = {
                        "name": user_input["group_name"] or new_group_id,
                        "controls": user_input["group_controls"],
                        "type": user_input["group_type"],
                        "icon": user_input.get("group_icon") or "",
                        "roles": group.get("roles", {}),
                        "expose_controls": group.get("expose_controls", []),
                        "objects": group.get("objects", {}),
                    }
                    self._pending_old_group_id = group_id
                    self._pending_group_id = new_group_id
                    self._pending_group = group_data
                    if user_input["group_type"] != TYPE_DEVICE:
                        return await self.async_step_edit_group_roles()
                    return await self.async_step_edit_group_objects()

        schema = vol.Schema(
            {
                vol.Required("group_id", default=group_id): str,
                vol.Required("group_name", default=group.get("name") or group_id): str,
                vol.Required("group_type", default=group.get("type") or default_group_type(group_id, group)): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_group_type_options())
                ),
                vol.Optional("group_icon", default=group.get("icon") or ""): str,
                vol.Required("group_controls", default=group.get("controls", [])): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_select_options(self._controls, groups, current_group_id=group_id),
                        multiple=True,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="edit_group_details", data_schema=schema, errors=errors)

    async def async_step_edit_group_roles(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())
        if not self._pending_group_id or not self._pending_group:
            return await self.async_step_edit_group()

        if user_input is not None:
            group = dict(self._pending_group)
            group["roles"] = _roles_from_input(user_input)
            group["expose_controls"] = user_input.get("expose_controls", [])
            self._pending_group = group
            return await self.async_step_edit_group_objects()

        schema = _role_schema(self._controls, self._pending_group)
        return self.async_show_form(step_id="edit_group_roles", data_schema=schema, errors=errors)

    async def async_step_add_group_objects(self, user_input: dict[str, Any] | None = None):
        return await self._async_step_group_objects("add_group_objects", "add_group_object", user_input)

    async def async_step_add_group_object(self, user_input: dict[str, Any] | None = None):
        return await self._async_step_group_object(user_input, "add_group_objects", "add_group_object")

    async def async_step_edit_group_objects(self, user_input: dict[str, Any] | None = None):
        return await self._async_step_group_objects("edit_group_objects", "edit_group_object", user_input)

    async def async_step_edit_group_object(self, user_input: dict[str, Any] | None = None):
        return await self._async_step_group_object(user_input, "edit_group_objects", "edit_group_object")

    async def _async_step_group_objects(
        self,
        step_id: str,
        object_step_id: str,
        user_input: dict[str, Any] | None = None,
    ):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())
        if not self._pending_group_id or not self._pending_group:
            return await self.async_step_init()

        if user_input is not None:
            if user_input["object_control"] == "__finish__":
                return self._create_group_entry()
            self._pending_object_key = user_input["object_control"]
            return await getattr(self, f"async_step_{object_step_id}")()

        group_controls = _group_controls(self._controls, self._pending_group)
        options = [
            selector.SelectOptionDict(value="__finish__", label="Finish / Готово"),
            *_select_options(group_controls or self._controls),
        ]
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Required("object_control", default="__finish__"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    ),
                }
            ),
            errors=errors,
        )

    async def _async_step_group_object(
        self,
        user_input: dict[str, Any] | None,
        list_step_id: str,
        step_id: str,
    ):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())
        if not self._pending_group_id or not self._pending_group or not self._pending_object_key:
            return await getattr(self, f"async_step_{list_step_id}")()

        control = self._controls.get(self._pending_object_key)
        if control is None:
            errors["base"] = "required"
            return await getattr(self, f"async_step_{list_step_id}")()

        if user_input is not None:
            group = dict(self._pending_group)
            objects = dict(group.get("objects") or {})
            if user_input.get("remove_object"):
                objects.pop(self._pending_object_key, None)
            else:
                objects[self._pending_object_key] = _object_override_from_input(user_input)
                if group.get("type") != TYPE_DEVICE:
                    expose_controls = set(group.get("expose_controls", []))
                    expose_controls.add(self._pending_object_key)
                    group["expose_controls"] = sorted(expose_controls)
            group["objects"] = objects
            self._pending_group = group
            self._pending_object_key = None
            return await getattr(self, f"async_step_{list_step_id}")()

        override = (self._pending_group.get("objects") or {}).get(self._pending_object_key, {})
        schema = vol.Schema(
            {
                vol.Optional(
                    "object_name",
                    default=override.get("name") or control.control_name or control.control_id,
                ): str,
                vol.Required(
                    "object_type",
                    default=override.get("device_class") or "auto",
                ): selector.SelectSelector(selector.SelectSelectorConfig(options=_object_device_class_options())),
                vol.Optional("object_icon", default=override.get("icon") or ""): str,
                vol.Optional("remove_object", default=False): bool,
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def async_step_remove_group(self, user_input: dict[str, Any] | None = None):
        groups = self._current_groups()
        if not groups:
            return self.async_show_form(
                step_id="remove_group",
                data_schema=vol.Schema({}),
                errors={"base": "no_groups"},
            )

        if user_input is not None:
            groups.pop(user_input["group_id"], None)
            return self.async_create_entry(
                title="",
                data=self._options_with(device_groups=groups),
            )

        schema = vol.Schema(
            {
                vol.Required("group_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_group_options(groups))
                ),
            }
        )
        return self.async_show_form(step_id="remove_group", data_schema=schema)

    async def async_step_export_config(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=self._options_with())

        export_json = self._export_json()
        return self.async_show_form(
            step_id="export_config",
            data_schema=vol.Schema(
                {
                    vol.Optional("export_json", default=export_json): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    ),
                }
            ),
        )

    async def async_step_import_config(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                payload = json.loads(user_input["import_json"])
                options = self._options_from_import(payload)
            except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                errors["base"] = "invalid_import"
            else:
                return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="import_config",
            data_schema=vol.Schema(
                {
                    vol.Required("import_json", default=""): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_diagnostics(self, user_input: dict[str, Any] | None = None):
        data = self._current_connection()
        try:
            snapshot = await self.hass.async_add_executor_job(
                discover_snapshot,
                data[CONF_HOST],
                data[CONF_PORT],
                data.get(CONF_USERNAME) or None,
                data.get(CONF_PASSWORD) or None,
                data[CONF_PREFIX],
            )
        except WBDiscoveryError:
            _LOGGER.exception("Cannot collect Wiren Board diagnostics")
            return self.async_show_form(
                step_id="diagnostics",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
            )

        devices = {control.device_id for control in snapshot.controls.values()}
        system_controls = [
            key for key, control in snapshot.controls.items() if _is_system_device(control.device_id)
        ]
        writable_controls = [
            key for key, control in snapshot.controls.items() if not control.is_readonly
        ]
        type_counts: dict[str, int] = {}
        for control in snapshot.controls.values():
            control_type = control.control_type or "unknown"
            type_counts[control_type] = type_counts.get(control_type, 0) + 1

        placeholders = {
            "device_count": str(len(devices)),
            "control_count": str(len(snapshot.controls)),
            "selected_count": str(len(self._current_selected_controls())),
            "group_count": str(len(self._current_groups())),
            "system_control_count": str(len(system_controls)),
            "writable_control_count": str(len(writable_controls)),
            "message_count": str(snapshot.message_count),
            "parse_errors": str(snapshot.parse_errors),
            "elapsed_seconds": str(snapshot.elapsed_seconds),
            "last_topic": snapshot.last_topic or "-",
            "last_payload": snapshot.last_payload or "-",
            "type_counts": ", ".join(f"{key}: {value}" for key, value in sorted(type_counts.items())),
        }
        return self.async_show_form(
            step_id="diagnostics",
            data_schema=vol.Schema({}),
            description_placeholders=placeholders,
        )

    async def _async_load_controls(self) -> dict[str, str]:
        if self._controls:
            return {}

        data = self._current_connection()
        try:
            self._controls = await self.hass.async_add_executor_job(
                discover_controls,
                data[CONF_HOST],
                data[CONF_PORT],
                data.get(CONF_USERNAME) or None,
                data.get(CONF_PASSWORD) or None,
                data[CONF_PREFIX],
            )
        except WBDiscoveryError:
            _LOGGER.exception("Cannot rediscover Wiren Board devices")
            return {"base": "cannot_connect"}
        return {}

    def _current_selected_controls(self) -> list[str]:
        return self._config_entry.options.get(
            CONF_SELECTED_CONTROLS,
            self._config_entry.data.get(CONF_SELECTED_CONTROLS, []),
        )

    def _current_groups(self) -> dict[str, dict[str, Any]]:
        groups = {}
        for key, value in self._config_entry.options.get(CONF_DEVICE_GROUPS, {}).items():
            group = dict(value)
            group.setdefault("type", default_group_type(key, group))
            group.setdefault("icon", "")
            group.setdefault("roles", {})
            group.setdefault("expose_controls", [])
            group.setdefault("objects", {})
            groups[key] = group
        return groups

    def _options_with(
        self,
        selected_controls: list[str] | None = None,
        device_groups: dict[str, dict[str, Any]] | None = None,
        show_system_devices: bool | None = None,
        connection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected = selected_controls if selected_controls is not None else self._current_selected_controls()
        groups = device_groups if device_groups is not None else self._current_groups()
        show_system = show_system_devices if show_system_devices is not None else self._show_system_devices()
        controls = {
            key: control_to_dict(control)
            for key, control in self._controls.items()
            if key in selected
        }
        existing_controls = self._config_entry.options.get(
            "discovered_controls",
            self._config_entry.data.get("discovered_controls", {}),
        )
        for key in selected:
            if key not in controls and key in existing_controls:
                controls[key] = existing_controls[key]
        return {
            CONF_SELECTED_CONTROLS: selected,
            "discovered_controls": controls,
            CONF_DEVICE_GROUPS: groups,
            CONF_SHOW_SYSTEM_DEVICES: show_system,
            **self._connection_options(connection),
        }

    def _show_system_devices(self) -> bool:
        return self._config_entry.options.get(
            CONF_SHOW_SYSTEM_DEVICES,
            self._config_entry.data.get(CONF_SHOW_SYSTEM_DEVICES, DEFAULT_SHOW_SYSTEM_DEVICES),
        )

    def _current_connection(self) -> dict[str, Any]:
        return {
            CONF_HOST: self._config_entry.options.get(CONF_HOST, self._config_entry.data[CONF_HOST]),
            CONF_PORT: self._config_entry.options.get(CONF_PORT, self._config_entry.data[CONF_PORT]),
            CONF_USERNAME: self._config_entry.options.get(
                CONF_USERNAME,
                self._config_entry.data.get(CONF_USERNAME, ""),
            ),
            CONF_PASSWORD: self._config_entry.options.get(
                CONF_PASSWORD,
                self._config_entry.data.get(CONF_PASSWORD, ""),
            ),
            CONF_PREFIX: self._config_entry.options.get(CONF_PREFIX, self._config_entry.data[CONF_PREFIX]),
            CONF_SHOW_SYSTEM_DEVICES: self._show_system_devices(),
        }

    def _connection_options(self, connection: dict[str, Any] | None = None) -> dict[str, Any]:
        data = connection or self._current_connection()
        return {
            CONF_HOST: data[CONF_HOST],
            CONF_PORT: data[CONF_PORT],
            CONF_USERNAME: data.get(CONF_USERNAME, ""),
            CONF_PASSWORD: data.get(CONF_PASSWORD, ""),
            CONF_PREFIX: data[CONF_PREFIX],
        }

    def _export_payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "domain": DOMAIN,
            "connection": self._connection_options(),
            "show_system_devices": self._show_system_devices(),
            "selected_controls": self._current_selected_controls(),
            "device_groups": self._current_groups(),
            "discovered_controls": self._config_entry.options.get(
                "discovered_controls",
                self._config_entry.data.get("discovered_controls", {}),
            ),
        }

    def _export_json(self) -> str:
        return json.dumps(self._export_payload(), ensure_ascii=False, indent=2, sort_keys=True)

    def _options_from_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("import payload must be an object")
        if payload.get("domain", DOMAIN) != DOMAIN:
            raise ValueError("wrong import domain")

        connection = payload.get("connection") or {}
        selected = [str(key) for key in payload.get("selected_controls", [])]
        groups = payload.get("device_groups") or {}
        discovered = payload.get("discovered_controls") or {}
        if not isinstance(groups, dict) or not isinstance(discovered, dict):
            raise ValueError("invalid import payload")

        return {
            CONF_SELECTED_CONTROLS: selected,
            "discovered_controls": discovered,
            CONF_DEVICE_GROUPS: groups,
            CONF_SHOW_SYSTEM_DEVICES: bool(payload.get("show_system_devices", DEFAULT_SHOW_SYSTEM_DEVICES)),
            CONF_HOST: str(connection.get(CONF_HOST, self._current_connection()[CONF_HOST])),
            CONF_PORT: int(connection.get(CONF_PORT, self._current_connection()[CONF_PORT])),
            CONF_USERNAME: str(connection.get(CONF_USERNAME, "")),
            CONF_PASSWORD: str(connection.get(CONF_PASSWORD, "")),
            CONF_PREFIX: str(connection.get(CONF_PREFIX, self._current_connection()[CONF_PREFIX])),
        }

    def _create_group_entry(self):
        if not self._pending_group_id or not self._pending_group:
            return self.async_create_entry(title="", data=self._options_with())

        groups = self._current_groups()
        if self._pending_old_group_id:
            groups.pop(self._pending_old_group_id, None)
        groups[self._pending_group_id] = self._pending_group

        selected = set(self._current_selected_controls())
        selected.update(self._pending_group.get("controls", []))
        self._clear_pending_group()
        self._edit_group_id = None
        return self.async_create_entry(
            title="",
            data=self._options_with(
                selected_controls=sorted(selected),
                device_groups=groups,
            ),
        )

    def _clear_pending_group(self) -> None:
        self._pending_group_id = None
        self._pending_group = None
        self._pending_old_group_id = None
        self._pending_object_key = None


def control_to_dict(control: WBControl) -> dict[str, Any]:
    return {
        "device_id": control.device_id,
        "control_id": control.control_id,
        "device_name": control.device_name,
        "control_name": control.control_name,
        "control_type": control.control_type,
        "readonly": control.readonly,
        "units": control.units,
        "value": control.value,
        "ha_device_id": control.ha_device_id,
        "ha_device_name": control.ha_device_name,
        "ha_entity_name": control.ha_entity_name,
        "ha_platform": control.ha_platform,
        "ha_device_class": control.ha_device_class,
        "ha_icon": control.ha_icon,
        "meta": control.meta,
    }


def control_from_dict(data: dict[str, Any]) -> WBControl:
    return WBControl(**data)


def _slug(value: str) -> str:
    original = value.strip()
    value = original.lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", value).strip("_")
    if slug:
        return slug
    if not original:
        return ""
    digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:10]
    return f"group_{digest}"


SYSTEM_DEVICE_IDS = {
    "network",
    "sms_sender",
    "system",
    "system_time",
    "wb-mqtt-gate",
    "wbrules",
}
SYSTEM_DEVICE_PREFIXES = (
    "system__",
    "wb-cloud-agent",
)


def _visible_controls(controls: dict[str, WBControl], show_system: bool) -> dict[str, WBControl]:
    if show_system:
        return controls
    return {
        key: control
        for key, control in controls.items()
        if not _is_system_device(control.device_id)
    }


def _is_system_device(device_id: str) -> bool:
    normalized = device_id.strip().lower()
    return normalized in SYSTEM_DEVICE_IDS or normalized.startswith(SYSTEM_DEVICE_PREFIXES)


def _group_options(groups: dict[str, dict[str, Any]]) -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=group_id,
            label=f"{group.get('name') or group_id} ({group_id})",
        )
        for group_id, group in sorted(groups.items())
    ]


def _control_membership(
    groups: dict[str, dict[str, Any]],
    current_group_id: str | None = None,
) -> dict[str, str]:
    membership: dict[str, str] = {}
    for group_id, group in groups.items():
        if group_id == current_group_id:
            continue
        group_name = group.get("name") or group_id
        for key in group.get("controls", []):
            membership[str(key)] = str(group_name)
    return membership


def _control_label(key: str, control: WBControl, membership: dict[str, str]) -> str:
    label = control.title
    if key in membership:
        label = f"{label} [{membership[key]}]"
    return label


def _group_type_options() -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(value=TYPE_DEVICE, label="Device / Обычное устройство"),
        selector.SelectOptionDict(value=TYPE_COVER_GATE, label="Gate / Ворота"),
        selector.SelectOptionDict(value=TYPE_COVER, label="Cover / Шторы, роллеты"),
        selector.SelectOptionDict(value=TYPE_THERMOSTAT, label="Thermostat / Термостат"),
        selector.SelectOptionDict(value=TYPE_AC, label="AC / Кондиционер"),
    ]


def _group_controls(controls: dict[str, WBControl], group: dict[str, Any]) -> dict[str, WBControl]:
    return {
        key: controls[key]
        for key in group.get("controls", [])
        if key in controls
    }


def _object_device_class_options() -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(value="auto", label="Auto / Авто"),
        selector.SelectOptionDict(value="switch", label="Switch / Выключатель"),
        selector.SelectOptionDict(value="outlet", label="Outlet / Розетка"),
        selector.SelectOptionDict(value="light", label="Light / Освещение"),
        selector.SelectOptionDict(value="fan", label="Fan / Вентилятор"),
        selector.SelectOptionDict(value="lock", label="Lock / Замок"),
        selector.SelectOptionDict(value="valve", label="Valve / Клапан"),
        selector.SelectOptionDict(value="garage", label="Garage / Ограждающее устройство"),
        selector.SelectOptionDict(value="siren", label="Siren / Сирена"),
        selector.SelectOptionDict(value="motion", label="Motion / Движение"),
        selector.SelectOptionDict(value="opening", label="Opening / Открытие"),
        selector.SelectOptionDict(value="problem", label="Problem / Проблема"),
        selector.SelectOptionDict(value="moisture", label="Moisture / Протечка"),
        selector.SelectOptionDict(value="connectivity", label="Connectivity / Связь"),
        selector.SelectOptionDict(value="battery", label="Battery / Батарея"),
        selector.SelectOptionDict(value="temperature", label="Temperature / Температура"),
        selector.SelectOptionDict(value="humidity", label="Humidity / Влажность"),
        selector.SelectOptionDict(value="power", label="Power / Мощность"),
        selector.SelectOptionDict(value="energy", label="Energy / Энергия"),
        selector.SelectOptionDict(value="voltage", label="Voltage / Напряжение"),
        selector.SelectOptionDict(value="current", label="Current / Ток"),
        selector.SelectOptionDict(value="illuminance", label="Illuminance / Освещенность"),
        selector.SelectOptionDict(value="signal_strength", label="Signal strength / Сигнал"),
    ]


def _object_override_from_input(user_input: dict[str, Any]) -> dict[str, str]:
    override = {
        "name": str(user_input.get("object_name") or "").strip(),
        "device_class": str(user_input.get("object_type") or "auto").strip(),
        "icon": str(user_input.get("object_icon") or "").strip(),
    }
    return {key: value for key, value in override.items() if value and value != "auto"}


def _role_options(controls: dict[str, WBControl], empty_label: str) -> list[selector.SelectOptionDict]:
    return [selector.SelectOptionDict(value="", label=empty_label)] + _select_options(controls)


ROLE_FIELDS = {
    "command_control": "command",
    "position_control": "position",
    "state_control": "state",
    "obstruction_control": "obstruction",
    "current_temperature_control": "current_temperature",
    "target_temperature_control": "target_temperature",
    "power_control": "power",
    "mode_control": "mode",
    "fan_control": "fan",
}

COVER_ROLE_FIELDS = {
    "command_control": "command",
    "position_control": "position",
    "state_control": "state",
    "obstruction_control": "obstruction",
}

CLIMATE_ROLE_FIELDS = {
    "current_temperature_control": "current_temperature",
    "target_temperature_control": "target_temperature",
    "power_control": "power",
    "mode_control": "mode",
    "fan_control": "fan",
}


def _role_schema(controls: dict[str, WBControl], group: dict[str, Any]) -> vol.Schema:
    group_controls = {
        key: controls[key]
        for key in group.get("controls", [])
        if key in controls
    }
    role_options = _role_options(group_controls or controls, "-")
    roles = group.get("roles") or {}
    group_type = group.get("type") or TYPE_DEVICE
    fields: dict[Any, Any] = {}

    role_fields = {}
    if group_type in {TYPE_COVER_GATE, TYPE_COVER}:
        role_fields = COVER_ROLE_FIELDS
    elif group_type in {TYPE_THERMOSTAT, TYPE_AC}:
        role_fields = CLIMATE_ROLE_FIELDS

    for field, role in role_fields.items():
        fields[vol.Optional(field, default=roles.get(role, ""))] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=role_options)
        )

    fields[vol.Optional("expose_controls", default=group.get("expose_controls", []))] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=_select_options(group_controls or controls), multiple=True)
    )
    return vol.Schema(fields)


def _roles_from_input(user_input: dict[str, Any]) -> dict[str, str]:
    return {
        role: user_input[field]
        for field, role in ROLE_FIELDS.items()
        if user_input.get(field)
    }
