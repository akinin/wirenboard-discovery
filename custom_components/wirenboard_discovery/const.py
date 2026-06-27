from __future__ import annotations

DOMAIN = "wirenboard_discovery"

CONF_PREFIX = "prefix"
CONF_SELECTED_CONTROLS = "selected_controls"
CONF_DEVICE_GROUPS = "device_groups"
CONF_SHOW_SYSTEM_DEVICES = "show_system_devices"

DEFAULT_HOST = ""
DEFAULT_PORT = 1883
DEFAULT_PREFIX = "/"
DEFAULT_SHOW_SYSTEM_DEVICES = False

PLATFORMS = [
    "binary_sensor",
    "button",
    "climate",
    "cover",
    "fan",
    "light",
    "lock",
    "number",
    "sensor",
    "siren",
    "switch",
    "text",
    "valve",
]

DISCOVERY_SECONDS = 4
