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
from homeassistant.helpers import entity_registry as er

from .composite import (
    COMPOSITE_TYPES,
    TYPE_AC,
    TYPE_COVER,
    TYPE_COVER_GATE,
    TYPE_DEVICE,
    TYPE_GAS,
    TYPE_THERMOSTAT,
    TYPE_WATER,
    default_group_type,
)
from .const import (
    CONF_DEVICE_GROUPS,
    CONF_INVERTED_BINARY_SENSORS,
    CONF_REMOVED_CONTROLS,
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

    async def async_step_zeroconf(self, discovery_info: Any):
        if not _is_wirenboard_zeroconf(discovery_info):
            return self.async_abort(reason="not_wirenboard")

        host = _zeroconf_host(discovery_info)
        unique_host = getattr(discovery_info, "host", None) or host
        await self.async_set_unique_id(f"{unique_host}:{DEFAULT_PORT}")
        self._abort_if_unique_id_configured()

        self._connection_data = {
            CONF_HOST: host,
            CONF_PORT: DEFAULT_PORT,
            CONF_USERNAME: "",
            CONF_PASSWORD: "",
            CONF_PREFIX: DEFAULT_PREFIX,
            CONF_SHOW_SYSTEM_DEVICES: DEFAULT_SHOW_SYSTEM_DEVICES,
        }
        try:
            self._controls = await self.hass.async_add_executor_job(
                discover_controls,
                host,
                DEFAULT_PORT,
                None,
                None,
                DEFAULT_PREFIX,
            )
        except WBDiscoveryError:
            _LOGGER.exception("Cannot discover Zeroconf Wiren Board device")
            return self.async_abort(reason="cannot_connect")

        self.context["title_placeholders"] = {
            "name": _zeroconf_name(discovery_info) or host,
            "host": host,
        }
        return await self.async_step_pick_controls()

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

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_group",
                "edit_group",
                "remove_group",
                "invert_binary_sensors",
                "remove_entities",
                "export_config",
                "import_config",
                "diagnostics",
                "connection",
            ],
        )

    async def async_step_remove_entities(
        self, user_input: dict[str, Any] | None = None
    ):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())
        selected = set(self._current_selected_controls())
        grouped = {
            str(key)
            for group in self._current_groups().values()
            for key in group.get("controls", [])
        }
        removable = {
            key: control
            for key, control in self._controls.items()
            if key in selected and key not in grouped
        }

        if user_input is not None:
            to_remove = set(user_input["entities_to_remove"])
            selected.difference_update(to_remove)
            removed = set(self._current_removed_controls())
            removed.update(to_remove)
            return self.async_create_entry(
                title="",
                data=self._options_with(
                    selected_controls=sorted(selected),
                    removed_controls=sorted(removed),
                ),
            )

        return self.async_show_form(
            step_id="remove_entities",
            data_schema=vol.Schema(
                {
                    vol.Required("entities_to_remove", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=self._entity_select_options(removable), multiple=True
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_invert_binary_sensors(
        self, user_input: dict[str, Any] | None = None
    ):
        errors: dict[str, str] = {}
        errors.update(await self._async_load_controls())
        selected = set(self._current_selected_controls())
        binary_controls = {
            key: control
            for key, control in self._controls.items()
            if key in selected
            and control.control_type == "switch"
            and control.is_readonly
        }

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=self._options_with(
                    inverted_binary_sensors=sorted(
                        user_input[CONF_INVERTED_BINARY_SENSORS]
                    )
                ),
            )

        inverted = [
            key
            for key in self._current_inverted_binary_sensors()
            if key in binary_controls
        ]
        return self.async_show_form(
            step_id="invert_binary_sensors",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INVERTED_BINARY_SENSORS, default=inverted
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=self._entity_select_options(binary_controls, "binary_sensor"),
                            multiple=True,
                        )
                    )
                }
            ),
            errors=errors,
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
                }
                selected = set(self._current_selected_controls())
                selected.update(user_input["group_controls"])
                removed_controls = set(self._current_removed_controls())
                removed_controls.difference_update(user_input["group_controls"])
                if user_input["group_type"] in COMPOSITE_TYPES:
                    self._pending_group_id = group_id
                    self._pending_group = groups[group_id]
                    self._pending_old_group_id = None
                    return await self.async_step_add_group_roles()
                return self.async_create_entry(
                    title="",
                    data=self._options_with(
                        selected_controls=sorted(selected),
                        removed_controls=sorted(removed_controls),
                        device_groups=groups,
                    ),
                )

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
            groups = self._current_groups()
            group = dict(self._pending_group)
            group["roles"] = _roles_from_input(user_input)
            group["expose_controls"] = user_input.get("expose_controls", [])
            groups[self._pending_group_id] = group
            selected = set(self._current_selected_controls())
            selected.update(group["controls"])
            removed_controls = set(self._current_removed_controls())
            removed_controls.difference_update(group["controls"])
            self._clear_pending_group()
            return self.async_create_entry(
                title="",
                data=self._options_with(
                    selected_controls=sorted(selected),
                    removed_controls=sorted(removed_controls),
                    device_groups=groups,
                ),
            )

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
                    }
                    old_controls = set(group.get("controls", []))
                    new_controls = set(user_input["group_controls"])
                    selected, removed_controls = self._selection_after_group_change(
                        groups,
                        added=new_controls,
                        removed=old_controls - new_controls,
                        replacing_group_id=group_id,
                    )
                    if user_input["group_type"] in COMPOSITE_TYPES:
                        self._pending_old_group_id = group_id
                        self._pending_group_id = new_group_id
                        self._pending_group = group_data
                        return await self.async_step_edit_group_roles()
                    groups[new_group_id] = group_data
                    self._edit_group_id = None
                    return self.async_create_entry(
                        title="",
                        data=self._options_with(
                            selected_controls=sorted(selected),
                            removed_controls=sorted(removed_controls),
                            device_groups=groups,
                        ),
                    )

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
            groups = self._current_groups()
            old_controls: set[str] = set()
            if self._pending_old_group_id:
                old_controls = set(
                    groups.get(self._pending_old_group_id, {}).get("controls", [])
                )
                groups.pop(self._pending_old_group_id, None)
            group = dict(self._pending_group)
            group["roles"] = _roles_from_input(user_input)
            group["expose_controls"] = user_input.get("expose_controls", [])
            groups[self._pending_group_id] = group
            selected, removed_controls = self._selection_after_group_change(
                groups,
                added=set(group["controls"]),
                removed=old_controls - set(group["controls"]),
            )
            self._clear_pending_group()
            self._edit_group_id = None
            return self.async_create_entry(
                title="",
                data=self._options_with(
                    selected_controls=sorted(selected),
                    removed_controls=sorted(removed_controls),
                    device_groups=groups,
                ),
            )

        schema = _role_schema(self._controls, self._pending_group)
        return self.async_show_form(step_id="edit_group_roles", data_schema=schema, errors=errors)

    async def async_step_remove_group(self, user_input: dict[str, Any] | None = None):
        groups = self._current_groups()
        if not groups:
            return self.async_show_form(
                step_id="remove_group",
                data_schema=vol.Schema({}),
                errors={"base": "no_groups"},
            )

        if user_input is not None:
            removed_group = groups.pop(user_input["group_id"], None) or {}
            selected, removed_controls = self._selection_after_group_change(
                groups,
                removed=set(removed_group.get("controls", [])),
            )
            return self.async_create_entry(
                title="",
                data=self._options_with(
                    selected_controls=sorted(selected),
                    removed_controls=sorted(removed_controls),
                    device_groups=groups,
                ),
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
        export_data = json.dumps(self._export_payload(), ensure_ascii=False, sort_keys=True)
        return self.async_show_form(
            step_id="export_config",
            data_schema=vol.Schema(
                {
                    vol.Optional("export_data", default=export_data): str,
                }
            ),
        )

    async def async_step_import_config(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                payload = json.loads(user_input["import_data"])
                options = self._options_from_import(payload)
            except (TypeError, ValueError, KeyError):
                errors["base"] = "invalid_import"
            else:
                return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="import_config",
            data_schema=vol.Schema({vol.Required("import_data"): str}),
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

    def _current_inverted_binary_sensors(self) -> list[str]:
        return self._config_entry.options.get(CONF_INVERTED_BINARY_SENSORS, [])

    def _current_removed_controls(self) -> list[str]:
        return list(self._config_entry.options.get(CONF_REMOVED_CONTROLS, []))

    def _entity_select_options(
        self, controls: dict[str, WBControl], domain: str | None = None
    ) -> list[selector.SelectOptionDict]:
        registry = er.async_get(self.hass)
        options: list[selector.SelectOptionDict] = []
        for key, control in sorted(controls.items()):
            label = control.title
            entity_id = (
                registry.async_get_entity_id(domain, DOMAIN, control.unique_id)
                if domain
                else next(
                    (
                        entry.entity_id
                        for entry in er.async_entries_for_config_entry(
                            registry, self._config_entry.entry_id
                        )
                        if entry.unique_id == control.unique_id
                    ),
                    None,
                )
            )
            if entity_id:
                entity = registry.async_get(entity_id)
                if entity and (entity.name or entity.original_name):
                    label = str(entity.name or entity.original_name)
            options.append(selector.SelectOptionDict(value=key, label=label))
        return options

    def _selection_after_group_change(
        self,
        groups: dict[str, dict[str, Any]],
        *,
        added: set[str] | None = None,
        removed: set[str] | None = None,
        replacing_group_id: str | None = None,
    ) -> tuple[set[str], set[str]]:
        added = added or set()
        removed = removed or set()
        controls_still_used = {
            str(key)
            for group_id, group in groups.items()
            if group_id != replacing_group_id
            for key in group.get("controls", [])
        }
        actually_removed = removed - controls_still_used - added
        selected = set(self._current_selected_controls())
        selected.difference_update(actually_removed)
        selected.update(added)
        removed_controls = set(self._current_removed_controls())
        removed_controls.update(actually_removed)
        removed_controls.difference_update(selected)
        return selected, removed_controls

    def _current_groups(self) -> dict[str, dict[str, Any]]:
        groups = {}
        for key, value in self._config_entry.options.get(CONF_DEVICE_GROUPS, {}).items():
            group = dict(value)
            group.setdefault("type", default_group_type(key, group))
            group.setdefault("icon", "")
            group.setdefault("roles", {})
            group.setdefault("expose_controls", [])
            groups[key] = group
        return groups

    def _options_with(
        self,
        selected_controls: list[str] | None = None,
        inverted_binary_sensors: list[str] | None = None,
        removed_controls: list[str] | None = None,
        device_groups: dict[str, dict[str, Any]] | None = None,
        show_system_devices: bool | None = None,
        connection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected = selected_controls if selected_controls is not None else self._current_selected_controls()
        inverted = (
            inverted_binary_sensors
            if inverted_binary_sensors is not None
            else self._current_inverted_binary_sensors()
        )
        removed = (
            removed_controls
            if removed_controls is not None
            else self._current_removed_controls()
        )
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
            CONF_INVERTED_BINARY_SENSORS: inverted,
            CONF_REMOVED_CONTROLS: removed,
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
            "inverted_binary_sensors": self._current_inverted_binary_sensors(),
            "device_groups": self._current_groups(),
            "discovered_controls": self._config_entry.options.get(
                "discovered_controls",
                self._config_entry.data.get("discovered_controls", {}),
            ),
        }

    def _options_from_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("import payload must be an object")
        if payload.get("domain", DOMAIN) != DOMAIN:
            raise ValueError("wrong import domain")

        connection = payload.get("connection") or {}
        selected = [str(key) for key in payload.get("selected_controls", [])]
        inverted = [str(key) for key in payload.get("inverted_binary_sensors", [])]
        groups = payload.get("device_groups") or {}
        discovered = payload.get("discovered_controls") or {}
        if not isinstance(groups, dict) or not isinstance(discovered, dict):
            raise ValueError("invalid import payload")

        return {
            CONF_SELECTED_CONTROLS: selected,
            CONF_INVERTED_BINARY_SENSORS: inverted,
            CONF_REMOVED_CONTROLS: [],
            "discovered_controls": discovered,
            CONF_DEVICE_GROUPS: groups,
            CONF_SHOW_SYSTEM_DEVICES: bool(payload.get("show_system_devices", DEFAULT_SHOW_SYSTEM_DEVICES)),
            CONF_HOST: str(connection.get(CONF_HOST, self._current_connection()[CONF_HOST])),
            CONF_PORT: int(connection.get(CONF_PORT, self._current_connection()[CONF_PORT])),
            CONF_USERNAME: str(connection.get(CONF_USERNAME, "")),
            CONF_PASSWORD: str(connection.get(CONF_PASSWORD, "")),
            CONF_PREFIX: str(connection.get(CONF_PREFIX, self._current_connection()[CONF_PREFIX])),
        }

    def _clear_pending_group(self) -> None:
        self._pending_group_id = None
        self._pending_group = None
        self._pending_old_group_id = None


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
        "meta": control.meta,
    }


def control_from_dict(data: dict[str, Any]) -> WBControl:
    return WBControl(**data)


def _is_wirenboard_zeroconf(discovery_info: Any) -> bool:
    values = [
        _zeroconf_name(discovery_info),
        getattr(discovery_info, "hostname", None),
        getattr(discovery_info, "server", None),
    ]
    return any(str(value or "").lower().startswith("wirenboard-") for value in values)


def _zeroconf_host(discovery_info: Any) -> str:
    hostname = getattr(discovery_info, "hostname", None)
    if hostname:
        return str(hostname).rstrip(".")
    host = getattr(discovery_info, "host", None)
    if host:
        return str(host)
    return _zeroconf_name(discovery_info) or DEFAULT_HOST


def _zeroconf_name(discovery_info: Any) -> str | None:
    name = getattr(discovery_info, "name", None)
    if not name:
        return None
    return str(name).split("._", 1)[0].strip()


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
        selector.SelectOptionDict(value=TYPE_GAS, label="Gas meter / Счётчик газа"),
        selector.SelectOptionDict(value=TYPE_WATER, label="Water meter / Счётчик воды"),
    ]


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
