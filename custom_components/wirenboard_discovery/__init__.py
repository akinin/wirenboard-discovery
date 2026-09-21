from __future__ import annotations

import asyncio
from dataclasses import replace
import logging
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType

from .config_flow import control_from_dict
from .composite import composite_control_keys, normalize_groups
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_MESSAGE,
    ATTR_PHONE,
    CONF_DEVICE_GROUPS,
    CONF_INVERTED_BINARY_SENSORS,
    CONF_REMOVED_CONTROLS,
    CONF_PREFIX,
    CONF_SELECTED_CONTROLS,
    DOMAIN,
    PLATFORMS,
    SERVICE_SEND_SMS,
)
from .device_registry_compat import device_belongs_to_entry, get_device_by_identifier
from .device_groups import async_apply_device_groups
from .models import WBControl
from .wb_mqtt import (
    WBDiscoveryError,
    WBRuntimeClient,
    control_metadata_signature,
    discover_controls,
    identity_metadata_key,
)

_LOGGER = logging.getLogger(__name__)

SEND_SMS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PHONE): cv.string,
        vol.Required(ATTR_MESSAGE): vol.All(cv.string, vol.Length(min=1, max=1000)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def async_send_sms(call: ServiceCall) -> None:
        entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
        runtime = hass.data.get(DOMAIN, {}).get(entry_id)
        if runtime is None:
            raise ServiceValidationError("Wiren Board configuration entry is not loaded")

        phone = _normalize_phone(call.data[ATTR_PHONE])
        message = call.data[ATTR_MESSAGE].strip()
        if not message:
            raise ServiceValidationError("SMS message must not be empty")

        client: WBRuntimeClient = runtime["client"]
        async with runtime["sms_lock"]:
            client.publish_control_by_id("sms_sender", "send", f"{phone};{message}")
            # wb-rules remembers the last value received on the command topic.
            # Clearing only the regular state topic from send_sms.js therefore
            # does not make an identical next command a change. Give the rule
            # time to accept the SMS, then reset the command topic to whitespace.
            # The rule trims and ignores that value, while wb-rules records it.
            await asyncio.sleep(1.0)
            client.publish_control_by_id("sms_sender", "send", " ")
            await asyncio.sleep(0.2)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_SMS,
        async_send_sms,
        schema=SEND_SMS_SCHEMA,
    )
    return True


def _normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s\-().]+", "", str(value).strip())
    if re.fullmatch(r"\+\d{7,15}", phone):
        return phone
    if re.fullmatch(r"7\d{10}", phone):
        return f"+{phone}"
    if re.fullmatch(r"8\d{10}", phone):
        return f"+7{phone[1:]}"
    if re.fullmatch(r"\d{10}", phone):
        return f"+7{phone}"
    raise ServiceValidationError("Phone number has an invalid format")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _remove_stale_control_entries(hass, entry)
    data = _entry_connection(entry)
    client = WBRuntimeClient(
        hass.loop,
        data[CONF_HOST],
        data[CONF_PORT],
        data.get(CONF_USERNAME) or None,
        data.get(CONF_PASSWORD) or None,
        data[CONF_PREFIX],
        hass.config.language,
    )

    async def stop_client(_event) -> None:
        await client.async_stop()

    cancel_stop_listener = None
    try:
        # Core shutdown does not necessarily unload config entries before
        # closing its event loop. Listen before starting the Paho worker too.
        cancel_stop_listener = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, stop_client
        )
        await client.async_start()
        controls = await _async_entry_controls(hass, entry, data)
        _remove_hidden_control_entries(hass, entry, controls)
        groups = normalize_groups(entry.options.get(CONF_DEVICE_GROUPS, {}))
        await async_apply_device_groups(hass, controls, groups)
        runtime = {
            "client": client,
            "sms_lock": asyncio.Lock(),
            "controls": controls,
            "groups": groups,
            "hidden_controls": composite_control_keys(groups),
            "inverted_binary_sensors": set(
                entry.options.get(CONF_INVERTED_BINARY_SENSORS, [])
            ),
        }
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _reconcile_control_devices(hass, entry, controls)
        _reconcile_device_identity(hass, entry, controls)
        _watch_selected_inventory(hass, entry, runtime)

        entry.async_on_unload(cancel_stop_listener)
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    except BaseException:
        if cancel_stop_listener is not None:
            cancel_stop_listener()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await client.async_stop()
        raise
    return True


def _remove_stale_control_entries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    removed = set(entry.options.get(CONF_REMOVED_CONTROLS, []))
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    removed_unique_ids = {
        re.sub(r"[^a-z0-9_]+", "_", f"wb_{key}".lower()).strip("_")
        for key in removed
    }
    affected_devices: set[str] = set()
    for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
        if entity.unique_id in removed_unique_ids:
            if entity.device_id:
                affected_devices.add(entity.device_id)
            entity_registry.async_remove(entity.entity_id)
    candidate_devices = affected_devices | {
        device.id
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    }
    for device_id in candidate_devices:
        device = device_registry.async_get(device_id)
        device_entities = er.async_entries_for_device(
            entity_registry, device_id, include_disabled_entities=True
        )
        if device and device_belongs_to_entry(device, entry.entry_id) and not device_entities:
            device_registry.async_remove_device(device_id)


def _remove_hidden_control_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    controls: dict[str, WBControl],
) -> None:
    """Remove registry entries for controls marked hidden by their publisher."""
    hidden_unique_ids = {
        control.unique_id for control in controls.values() if control.is_hidden
    }
    if not hidden_unique_ids:
        return

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    affected_devices: set[str] = set()
    for entity in list(
        er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    ):
        if entity.unique_id not in hidden_unique_ids:
            continue
        if entity.device_id:
            affected_devices.add(entity.device_id)
        entity_registry.async_remove(entity.entity_id)

    for device_id in affected_devices:
        device = device_registry.async_get(device_id)
        device_entities = er.async_entries_for_device(
            entity_registry, device_id, include_disabled_entities=True
        )
        if device and device_belongs_to_entry(device, entry.entry_id) and not device_entities:
            device_registry.async_remove_device(device_id)


def _reconcile_control_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    controls: dict[str, WBControl],
) -> None:
    """Move existing entities when a control joins or leaves a logical group."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entries = {
        entity.unique_id: entity
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }
    previous_devices: set[str] = set()

    for control in controls.values():
        entity = entries.get(control.unique_id)
        if entity is None:
            continue
        device_identifier = control.ha_device_id or control.device_id
        expected_device = get_device_by_identifier(
            device_registry, device_identifier, entry.entry_id
        )
        if expected_device is None:
            expected_device = device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, device_identifier)},
                name=(
                    control.ha_device_name
                    or control.device_name
                    or control.device_id
                ),
                manufacturer="Wiren Board",
            )
        if entity.device_id == expected_device.id:
            continue
        if entity.device_id:
            previous_devices.add(entity.device_id)
        entity_registry.async_update_entity(
            entity.entity_id, device_id=expected_device.id
        )

    for device_id in previous_devices:
        device = device_registry.async_get(device_id)
        device_entities = er.async_entries_for_device(
            entity_registry, device_id, include_disabled_entities=True
        )
        if device and device_belongs_to_entry(device, entry.entry_id) and not device_entities:
            device_registry.async_remove_device(device_id)


def _reconcile_device_identity(
    hass: HomeAssistant,
    entry: ConfigEntry,
    controls: dict[str, WBControl],
) -> None:
    """Apply identity controls after platform devices have been registered."""
    stored = _entry_controls(entry)
    updates_by_identifier: dict[str, dict[str, str]] = {}
    for key, control in controls.items():
        identity_key = identity_metadata_key(control.control_id)
        if identity_key not in {"serial_number", "sw_version", "hw_version"}:
            continue
        value = control.value
        if value is None or not str(value).strip():
            previous = stored.get(key)
            value = previous.value if previous else None
        if value is None or not str(value).strip():
            continue
        identifier = control.ha_device_id or control.device_id
        updates_by_identifier.setdefault(identifier, {})[identity_key] = str(value)

    registry = dr.async_get(hass)
    for identifier, updates in updates_by_identifier.items():
        device = get_device_by_identifier(registry, identifier, entry.entry_id)
        if device is not None:
            registry.async_update_device(device.id, **updates)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["client"].async_stop()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _watch_selected_inventory(
    hass: HomeAssistant, entry: ConfigEntry, runtime: dict
) -> None:
    """Reload only this integration entry when selected MQTT metadata changes."""
    client: WBRuntimeClient = runtime["client"]
    selected = set(
        entry.options.get(
            CONF_SELECTED_CONTROLS, entry.data.get(CONF_SELECTED_CONTROLS, [])
        )
    )
    runtime["inventory_signature"] = _selected_inventory_signature(client, selected)
    runtime["inventory_reload_cancel"] = None
    runtime["inventory_armed"] = False

    async def async_reload(_now) -> None:
        runtime["inventory_reload_cancel"] = None
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_reload(entry.entry_id)

    def inventory_changed() -> None:
        if not runtime["inventory_armed"]:
            return
        signature = _selected_inventory_signature(client, selected)
        if signature == runtime["inventory_signature"]:
            return
        runtime["inventory_signature"] = signature
        cancel = runtime.get("inventory_reload_cancel")
        if cancel:
            cancel()
        runtime["inventory_reload_cancel"] = async_call_later(
            hass, 2.0, async_reload
        )

    def cleanup() -> None:
        cancel = runtime.get("inventory_reload_cancel")
        if cancel:
            cancel()
            runtime["inventory_reload_cancel"] = None

    @callback
    def arm_inventory(_now) -> None:
        runtime["inventory_signature"] = _selected_inventory_signature(
            client, selected
        )
        runtime["inventory_armed"] = True

    entry.async_on_unload(client.subscribe_inventory(inventory_changed))
    entry.async_on_unload(async_call_later(hass, 120.0, arm_inventory))
    entry.async_on_unload(cleanup)


def _selected_inventory_signature(
    client: WBRuntimeClient, selected: set[str]
) -> tuple:
    return tuple(
        (
            key,
            control_metadata_signature(client.controls[key])
            if key in client.controls
            else None,
        )
        for key in sorted(selected)
    )


def _entry_controls(entry: ConfigEntry) -> dict[str, WBControl]:
    stored = entry.options.get("discovered_controls") or entry.data.get("discovered_controls", {})
    selected = entry.options.get(CONF_SELECTED_CONTROLS, entry.data.get(CONF_SELECTED_CONTROLS, []))
    return {
        key: control_from_dict(value)
        for key, value in stored.items()
        if key in selected
    }


async def _async_entry_controls(
    hass: HomeAssistant, entry: ConfigEntry, connection: dict
) -> dict[str, WBControl]:
    """Refresh retained metadata on startup, falling back to stored discovery."""
    stored = _entry_controls(entry)
    selected = set(
        entry.options.get(
            CONF_SELECTED_CONTROLS, entry.data.get(CONF_SELECTED_CONTROLS, [])
        )
    )
    try:
        discovered = await hass.async_add_executor_job(
            discover_controls,
            connection[CONF_HOST],
            connection[CONF_PORT],
            connection.get(CONF_USERNAME) or None,
            connection.get(CONF_PASSWORD) or None,
            connection[CONF_PREFIX],
        )
    except WBDiscoveryError:
        _LOGGER.warning(
            "Cannot refresh Wiren Board metadata; using stored controls",
            exc_info=True,
        )
        return stored

    if not discovered:
        _LOGGER.warning("Wiren Board metadata refresh returned no controls")
        return stored
    refreshed: dict[str, WBControl] = {}
    for key, control in discovered.items():
        if key not in selected:
            continue
        previous = stored.get(key)
        if (
            (control.value is None or not str(control.value).strip())
            and previous
            and previous.value is not None
            and str(previous.value).strip()
        ):
            control = replace(control, value=previous.value)
        refreshed[key] = control
    return refreshed


def _entry_connection(entry: ConfigEntry) -> dict:
    return {
        CONF_HOST: entry.options.get(CONF_HOST, entry.data[CONF_HOST]),
        CONF_PORT: entry.options.get(CONF_PORT, entry.data[CONF_PORT]),
        CONF_USERNAME: entry.options.get(CONF_USERNAME, entry.data.get(CONF_USERNAME, "")),
        CONF_PASSWORD: entry.options.get(CONF_PASSWORD, entry.data.get(CONF_PASSWORD, "")),
        CONF_PREFIX: entry.options.get(CONF_PREFIX, entry.data[CONF_PREFIX]),
    }
