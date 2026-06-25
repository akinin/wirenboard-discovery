from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

from .const import (
    CONF_DEVICE_GROUPS,
    CONF_PREFIX,
    CONF_SELECTED_CONTROLS,
    CONF_SHOW_SYSTEM_DEVICES,
    DEFAULT_SHOW_SYSTEM_DEVICES,
    DOMAIN,
)


def build_export_payload(entry: ConfigEntry) -> dict[str, Any]:
    """Build a portable backup for the integration options."""
    return {
        "version": 1,
        "domain": DOMAIN,
        "connection": {
            CONF_HOST: entry.options.get(CONF_HOST, entry.data.get(CONF_HOST)),
            CONF_PORT: entry.options.get(CONF_PORT, entry.data.get(CONF_PORT)),
            CONF_USERNAME: entry.options.get(CONF_USERNAME, entry.data.get(CONF_USERNAME, "")),
            CONF_PASSWORD: entry.options.get(CONF_PASSWORD, entry.data.get(CONF_PASSWORD, "")),
            CONF_PREFIX: entry.options.get(CONF_PREFIX, entry.data.get(CONF_PREFIX, "/")),
        },
        "show_system_devices": entry.options.get(
            CONF_SHOW_SYSTEM_DEVICES,
            entry.data.get(CONF_SHOW_SYSTEM_DEVICES, DEFAULT_SHOW_SYSTEM_DEVICES),
        ),
        "selected_controls": entry.options.get(
            CONF_SELECTED_CONTROLS,
            entry.data.get(CONF_SELECTED_CONTROLS, []),
        ),
        "device_groups": entry.options.get(CONF_DEVICE_GROUPS, {}),
        "discovered_controls": entry.options.get(
            "discovered_controls",
            entry.data.get("discovered_controls", {}),
        ),
    }
