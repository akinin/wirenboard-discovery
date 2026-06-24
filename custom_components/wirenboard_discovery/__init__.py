from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .config_flow import control_from_dict
from .composite import composite_control_keys, normalize_groups
from .const import CONF_DEVICE_GROUPS, CONF_PREFIX, CONF_SELECTED_CONTROLS, DOMAIN, PLATFORMS
from .device_groups import apply_device_groups
from .models import WBControl
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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
        "controls": controls,
        "groups": groups,
        "hidden_controls": composite_control_keys(groups),
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


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
