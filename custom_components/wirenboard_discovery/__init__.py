from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .config_flow import control_from_dict
from .composite import CLIMATE_TYPES, COVER_TYPES, composite_control_keys, group_type, normalize_groups
from .const import CONF_DEVICE_GROUPS, CONF_PREFIX, CONF_SELECTED_CONTROLS, DOMAIN, PLATFORMS
from .device_groups import apply_device_groups
from .entity import platform_for_control
from .models import WBControl
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {})
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
    hidden_controls = composite_control_keys(groups)
    _cleanup_stale_entities(hass, entry, controls, groups, hidden_controls)
    domain_data[entry.entry_id] = {
        "client": client,
        "controls": controls,
        "groups": groups,
        "hidden_controls": hidden_controls,
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


def _cleanup_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    controls: dict[str, WBControl],
    groups: dict[str, dict],
    hidden_controls: set[str],
) -> None:
    registry = er.async_get(hass)
    expected = _expected_entities(controls, groups, hidden_controls)
    for entity in list(registry.entities.values()):
        if getattr(entity, "config_entry_id", None) != entry.entry_id:
            continue
        unique_id = getattr(entity, "unique_id", None)
        domain = getattr(entity, "domain", None)
        if not unique_id or not str(unique_id).startswith("wb_"):
            continue
        if (domain, unique_id) not in expected:
            registry.async_remove(entity.entity_id)


def _expected_entities(
    controls: dict[str, WBControl],
    groups: dict[str, dict],
    hidden_controls: set[str],
) -> set[tuple[str, str]]:
    expected: set[tuple[str, str]] = set()
    for control in controls.values():
        if control.key in hidden_controls:
            continue
        platform = platform_for_control(control)
        if platform is not None:
            expected.add((platform, control.unique_id))

    for group_id, group in groups.items():
        current_group_type = group_type(group)
        if current_group_type in COVER_TYPES:
            expected.add(("cover", f"wb_group_{group_id}_cover"))
        if current_group_type in CLIMATE_TYPES:
            expected.add(("climate", f"wb_group_{group_id}_climate"))
    return expected
