from __future__ import annotations

import asyncio
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
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
    CONF_SENSOR_DEVICE_CLASSES,
    CONF_PREFIX,
    CONF_SELECTED_CONTROLS,
    DOMAIN,
    PLATFORMS,
    SERVICE_SEND_SMS,
)
from .device_groups import apply_device_groups
from .models import WBControl
from .wb_mqtt import WBRuntimeClient

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
    )
    await client.async_start()

    controls = _entry_controls(entry)
    groups = normalize_groups(entry.options.get(CONF_DEVICE_GROUPS, {}))
    apply_device_groups(hass, controls, groups)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "sms_lock": asyncio.Lock(),
        "controls": controls,
        "groups": groups,
        "hidden_controls": composite_control_keys(groups),
        "inverted_binary_sensors": set(
            entry.options.get(CONF_INVERTED_BINARY_SENSORS, [])
        ),
        "sensor_device_classes": entry.options.get(CONF_SENSOR_DEVICE_CLASSES, {}),
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _remove_stale_control_entries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    removed = set(entry.options.get(CONF_REMOVED_CONTROLS, []))
    if not removed:
        return
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
    remaining_device_ids = {
        entity.device_id
        for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if entity.device_id
    }
    for device_id in affected_devices - remaining_device_ids:
        device = device_registry.async_get(device_id)
        if device and entry.entry_id in device.config_entries:
            device_registry.async_remove_device(device_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["client"].async_stop()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _entry_controls(entry: ConfigEntry) -> dict[str, WBControl]:
    stored = entry.options.get("discovered_controls") or entry.data.get("discovered_controls", {})
    selected = entry.options.get(CONF_SELECTED_CONTROLS, entry.data.get(CONF_SELECTED_CONTROLS, []))
    return {
        key: control_from_dict(value)
        for key, value in stored.items()
        if key in selected
    }


def _entry_connection(entry: ConfigEntry) -> dict:
    return {
        CONF_HOST: entry.options.get(CONF_HOST, entry.data[CONF_HOST]),
        CONF_PORT: entry.options.get(CONF_PORT, entry.data[CONF_PORT]),
        CONF_USERNAME: entry.options.get(CONF_USERNAME, entry.data.get(CONF_USERNAME, "")),
        CONF_PASSWORD: entry.options.get(CONF_PASSWORD, entry.data.get(CONF_PASSWORD, "")),
        CONF_PREFIX: entry.options.get(CONF_PREFIX, entry.data[CONF_PREFIX]),
    }
